"""
Rich Messages (Bot API 10.1+): klien HTTP + pembangun konten.

python-telegram-bot 21.11.1 belum punya method `sendRichMessage`, jadi dipanggil langsung
lewat HTTP. Modul ini sengaja tidak mengimpor `config` supaya fungsi murninya mudah dites.

Model tombol: dict {"type", "label", "value", "style", "join"}
  type  : link | copy | share | chat | popup | vote
  join  : True = satu baris dengan tombol sebelumnya (maks MAX_ROW per baris)
Model urutan isi: daftar `blocks`. Entri khusus "@media" (foto/video utama) dan "@text"
(judul + isi utama) bisa digeser bebas di antara blok lain.
"""
import asyncio
import html
import re
from urllib.parse import quote

import httpx

MAX_RICH_CHARS = 32768       # batas isi Rich Message
MAX_CAPTION = 1024           # batas caption pesan biasa (fallback)
MAX_BUTTONS = 12             # total tombol
MAX_ROW = 8                  # tombol per baris (batas Telegram)
MAX_VOTES = 8

# Warna tombol (Bot API 10.3). Kosong = warna bawaan aplikasi.
BTN_STYLES = {"biru": "primary", "primary": "primary", "hijau": "success", "success": "success",
              "merah": "danger", "danger": "danger", "polos": "", "default": "", "normal": ""}
ALIGNS = ["left", "center", "right"]
ALIGN_LABEL = {"left": "Kiri", "center": "Tengah", "right": "Kanan"}

# Jenis tombol. Tombol berjenis URL dan popup bisa ditaruh DALAM teks; Salin dan Vote hanya di bawah pesan.
BTN_TYPES = {
    "link": ("🔗", "Link"), "copy": ("📋", "Salin"), "share": ("📤", "Bagikan"),
    "chat": ("💬", "Chat"), "popup": ("💡", "Popup"), "vote": ("👍", "Vote"),
}
BTN_ORDER = ["link", "copy", "share", "chat", "popup", "vote"]
INTEXT_TYPES = ("link", "share", "chat", "popup")
BTN_HELP = {
    "link": ("Buka link", "Teks | https://contoh.com"),
    "copy": ("Menyalin teks ke clipboard (kode promo, nomor rekening, dll)", "Salin Kode | PROMO50"),
    "share": ("Membuka daftar chat untuk membagikan sebuah link", "Bagikan | https://t.me/namachannel"),
    "chat": ("Membuka chat ke akun / channel / bot", "Hubungi Admin | @username"),
    "popup": ("Memunculkan jendela info saat ditekan (maks 200 karakter)", "Info | Diskon berlaku sampai Jumat"),
    "vote": ("Tombol reaksi dengan hitungan suara. Satu orang satu suara", "👍 Suka"),
}
_PREFIX = {"salin": "copy", "copy": "copy", "bagikan": "share", "share": "share", "chat": "chat",
           "hubungi": "chat", "popup": "popup", "info": "popup", "vote": "vote", "link": "link"}
_PREFIX_RE = re.compile(r"^(" + "|".join(_PREFIX) + r")\s*:\s*(.*)$", re.I | re.S)

# Penanda posisi tombol di dalam isi: `{tombol}` (semua) atau `{tombol:2}` (tombol nomor 2), di baris sendiri.
_MARKER_RE = re.compile(r"(?m)^[ \t]*\{tombol(?::(\d+))?\}[ \t]*$\n?", re.I)

STYLES = ["normal", "quote", "expand", "details", "aside"]
STYLE_LABEL = {
    "normal": "Normal",
    "quote": "Kutipan",
    "expand": "Kutipan lipat",
    "details": "Teks lipat",
    "aside": "Panel",
}
_BLOCK_TAGS = ("<blockquote", "<pre", "<details", "<table", "<ul", "<ol", "<h1", "<h2", "<h3", "<aside")


class RichError(Exception):
    """Error dari Bot API (membawa deskripsi asli Telegram)."""

    def __init__(self, description: str, code: int | None = None, retry_after: int | None = None):
        super().__init__(description)
        self.description = description
        self.code = code
        self.retry_after = retry_after


# ── Tombol ────────────────────────────────────────────────────────────────────

def norm_button(b) -> dict:
    """Terima tuple lama (teks, url[, warna]) atau dict; kembalikan dict lengkap."""
    if isinstance(b, dict):
        d = dict(b)
        d.setdefault("type", "link")
        d.setdefault("value", "")
        d.setdefault("style", "")
        d.setdefault("join", False)
        return d
    return {"type": "link", "label": b[0], "value": b[1], "style": b[2] if len(b) > 2 else "", "join": False}


def prepare_buttons(buttons: list | None, cols: int = 0) -> list[dict]:
    """Normalisasi + nomor urut `_i` (dipakai penanda {tombol:N}). cols>1 menyusun otomatis N per baris."""
    out = []
    for i, b in enumerate(buttons or []):
        d = norm_button(b)
        d["_i"] = i
        if cols and cols > 1:
            d["join"] = i % cols != 0
        out.append(d)
    return out


def rows_of(buttons: list[dict]) -> list[list[dict]]:
    """Kelompokkan tombol jadi baris sesuai flag `join` (maks MAX_ROW per baris)."""
    rows: list[list[dict]] = []
    for b in buttons:
        if rows and b.get("join") and len(rows[-1]) < MAX_ROW:
            rows[-1].append(b)
        else:
            rows.append([b])
    return rows


def button_url(b: dict) -> str:
    if b["type"] == "share":
        return "https://t.me/share/url?url=" + quote(b["value"], safe="")
    return b["value"]


def split_buttons(buttons: list | None, inline: bool, cols: int = 0) -> tuple[list[dict], list[dict]]:
    """(tombol_dalam_teks, tombol_di_bawah). Tombol Salin dan Vote selalu di bawah."""
    btns = prepare_buttons(buttons, cols)
    if not inline:
        return [], btns
    intext, below, prev_in = [], [], None
    for b in btns:
        in_text = b["type"] in INTEXT_TYPES
        if prev_in is not None and prev_in != in_text:
            b["join"] = False                    # beda tempat (dalam teks / di bawah): mulai baris baru
        (intext if in_text else below).append(b)
        prev_in = in_text
    return intext, below


def _button_tag(b: dict, cb: dict | None) -> str:
    st = f' style="{b["style"]}"' if b.get("style") else ""
    label = _esc(b["label"])
    if b["type"] == "popup":
        data = (cb or {}).get(b["_i"], "rpp:0")
        return f'<tg-button type="callback_data" data="{html.escape(data, quote=True)}"{st}>{label}</tg-button>'
    return f'<tg-button type="url" url="{html.escape(button_url(b), quote=True)}"{st}>{label}</tg-button>'


def button_rows(buttons: list, align: str = "left", cb: dict | None = None, cols: int = 0) -> str:
    """Tombol dalam teks: satu <tg-button-row> per baris susunan."""
    attr = f' align="{align}"' if align in ("center", "right") else ""
    bs = buttons if buttons and isinstance(buttons[0], dict) and "_i" in buttons[0] else prepare_buttons(buttons, cols)
    return "".join(f"<tg-button-row{attr}>" + "".join(_button_tag(b, cb) for b in row) + "</tg-button-row>"
                   for row in rows_of(bs))


def inline_markup(buttons: list | None, cb: dict | None = None, meta: bool = False) -> dict | None:
    """inline_keyboard biasa (dict JSON) untuk tombol 'di bawah'. meta=True menambah _vote/_label (disimpan di DB)."""
    bs = buttons if buttons and isinstance(buttons[0], dict) and "_i" in buttons[0] else prepare_buttons(buttons)
    if not bs:
        return None
    rows = []
    for row in rows_of(bs):
        r = []
        for b in row:
            it: dict = {"text": b["label"]}
            t = b["type"]
            if t == "copy":
                it["copy_text"] = {"text": b["value"]}
            elif t == "popup":
                it["callback_data"] = (cb or {}).get(b["_i"], "rpp:0")
            elif t == "vote":
                data = (cb or {}).get(b["_i"], "rpv:0:0")
                it["callback_data"] = data
                if meta:
                    it["_vote"] = int(data.rsplit(":", 1)[1])
                    it["_label"] = b["label"]
            else:
                it["url"] = button_url(b)
            if b.get("style"):
                it["style"] = b["style"]
            r.append(it)
        rows.append(r)
    return {"inline_keyboard": rows}


def clean_markup(markup: dict, counts: dict | None = None) -> dict:
    """Markup tersimpan (dengan _vote/_label) -> markup siap kirim, label vote diberi hitungan."""
    counts = counts or {}
    rows = []
    for row in markup.get("inline_keyboard", []):
        r = []
        for it in row:
            it = dict(it)
            if "_vote" in it:
                n = counts.get(it["_vote"], 0)
                it["text"] = f"{it['_label']} · {n}" if n else it["_label"]
            it.pop("_vote", None)
            it.pop("_label", None)
            r.append(it)
        rows.append(r)
    return {"inline_keyboard": rows}


def buttons_markup(buttons: list | None) -> dict | None:
    """Kompatibilitas: inline_keyboard sederhana dari daftar tombol (tanpa popup/vote)."""
    return inline_markup(prepare_buttons(buttons)) if buttons else None


def buttons_summary(buttons: list | None) -> str:
    """Tampilan susunan baris untuk teks di bot, contoh: '1. [📋 Salin] [📤 Bagikan]'."""
    out = []
    for n, row in enumerate(rows_of(prepare_buttons(buttons)), 1):
        out.append(f"{n}. " + " ".join(f"[{BTN_TYPES[b['type']][0]} {_esc(b['label'][:20])}]" for b in row))
    return "\n".join(out)


# ── Pembangun konten ──────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return html.escape(s or "", quote=False)


def _newlines(body: str) -> str:
    """Baris baru jadi <br/> (HTML meratakan newline), kecuali ada blok <pre>."""
    return body if "<pre" in body else body.replace("\n", "<br/>")


def _has_block(body: str) -> bool:
    return any(t in body for t in _BLOCK_TAGS)


def strip_markers(body: str) -> str:
    """Hapus penanda `{tombol}` dari isi (dipakai saat tombol tidak ditaruh di dalam teks)."""
    return _MARKER_RE.sub("", body or "")


def _segments(body: str, intext: list[dict], append_rest: bool = True) -> list:
    """Pecah isi di penanda tombol. Return [("text", str) | ("btn", [tombol...])].
    Tombol dalam teks yang belum ditempatkan penanda mana pun ditaruh di akhir isi (jika append_rest)."""
    by_i = {b["_i"]: b for b in intext}
    pieces = _MARKER_RE.split(body)             # [teks, nomor|None, teks, nomor|None, ..., teks]
    segs, placed = [], set()
    for i in range(0, len(pieces), 2):
        segs.append(("text", pieces[i]))
        if i + 1 < len(pieces):
            n = pieces[i + 1]
            idx = list(by_i) if n is None else ([int(n) - 1] if int(n) - 1 in by_i else [])
            placed.update(idx)
            if idx:
                segs.append(("btn", [by_i[k] for k in idx]))
    rest = [b for k, b in by_i.items() if k not in placed]
    if rest and append_rest:
        segs.append(("btn", rest))
    return segs


_MARK_RE = re.compile(r"==(?=\S)(.+?)(?<=\S)==")


def _prep(seg: str) -> str:
    """Baris baru jadi <br/> dan ==sorot== jadi <mark>."""
    seg = _newlines(seg.strip("\n"))
    return seg if "<pre" in seg else _MARK_RE.sub(r"<mark>\1</mark>", seg)


def _wrap_text(seg: str, style: str, spoiler: bool) -> str:
    seg = _prep(seg)
    if not seg.strip():
        return ""
    if spoiler:
        seg = f"<tg-spoiler>{seg}</tg-spoiler>"
    if style == "quote":
        return f"<blockquote>{seg}</blockquote>"
    if style == "expand":
        return f"<blockquote expandable>{seg}</blockquote>"
    if style == "aside":
        return f"<aside>{seg}</aside>"
    return seg if _has_block(seg) else f"<p>{seg}</p>"


def _figcaption(caption: str) -> str:
    return f"<figcaption>{_esc(caption)}</figcaption>" if caption else ""


def _text_group(body: str, *, style: str, title: str, title_size: int, spoiler: bool,
                intext: list[dict], append_rest: bool, align: str, cb: dict | None) -> str:
    """Judul + isi utama (dengan tombol dalam teks)."""
    parts: list[str] = []
    segs = _segments(body, intext, append_rest) if intext else [("text", body)]
    if title and style != "details":
        size = max(1, min(int(title_size or 2), 6))
        parts.append(f"<h{size}>{_esc(title)}</h{size}>")
    if style == "details":
        inner = []
        for kind, val in segs:
            if kind == "btn":
                inner.append(button_rows(val, align, cb))
            elif val.strip():
                t = _prep(val)
                inner.append(f"<tg-spoiler>{t}</tg-spoiler>" if spoiler else t)
        if inner:
            parts.append(f"<details><summary>{_esc(title) or 'Selengkapnya'}</summary>{''.join(inner)}</details>")
    else:
        for kind, val in segs:
            parts.append(button_rows(val, align, cb) if kind == "btn" else _wrap_text(val, style, spoiler))
    return "".join(parts)


def build_rich_html(body_html: str, *, style: str = "normal", title: str = "", spoiler: bool = False,
                    divider: bool = False, footer: str = "", media_kind: str | None = None,
                    media_id: str = "m1", buttons: list | None = None, buttons_inline: bool = False,
                    cols: int = 0, align: str = "left", blocks: list | None = None,
                    title_size: int = 2, cb: dict | None = None) -> str:
    """Susun Rich HTML dari isi pesan (HTML ala Telegram), blok tambahan, dan opsi format.

    Urutan mengikuti `blocks`. Entri "@media" dan "@text" menempatkan media utama dan teks utama.
    Bila keduanya tidak ada di `blocks` (pemakaian lama), media dan teks ditaruh paling atas.
    Tombol URL/popup masuk ke HTML bila `buttons_inline` True. Tombol lain (Salin, Vote) dan semua tombol
    pada mode 'di bawah' dikirim terpisah lewat `inline_markup`."""
    blocks = blocks or []
    intext, _below = split_buttons(buttons, buttons_inline, cols)
    block_btns = bool(intext) and any(b.get("t") == "btns" for b in blocks)   # blok "Tombol" menentukan posisinya sendiri
    body = (body_html or "").strip()
    if not intext:
        body = strip_markers(body).strip()

    def media_html() -> str:
        if media_kind not in ("photo", "video"):
            return ""
        tag = "img" if media_kind == "photo" else "video"
        sp = " tg-spoiler" if spoiler else ""
        return f'<figure><{tag} src="tg://{media_kind}?id={media_id}"{sp}/></figure>'

    def text_html() -> str:
        return _text_group(body, style=style, title=title, title_size=title_size, spoiler=spoiler,
                           intext=intext, append_rest=not block_btns, align=align, cb=cb)

    seq: list[tuple] = [(bi, b) for bi, b in enumerate(blocks)]
    if not any(b.get("t") == "@text" for b in blocks):
        seq = [(None, {"t": "@media"}), (None, {"t": "@text"})] + seq
    parts: list[str] = []
    for bi, b in seq:
        t = b.get("t")
        if t == "@media":
            parts.append(media_html())
        elif t == "@text":
            parts.append(text_html())
        elif t == "btns":
            if intext:
                parts.append(button_rows(intext, align, cb))
        else:
            parts.append(render_block(b, bi))
    if divider:
        parts.append("<hr/>")
    if footer:
        parts.append(f"<footer>{_esc(footer)}</footer>")
    return "".join(parts)


def build_plain_html(body_html: str, *, style: str = "normal", title: str = "", spoiler: bool = False,
                     footer: str = "", blocks: list | None = None) -> str:
    """Versi pesan biasa (parse_mode=HTML) dipakai sebagai cadangan jika Rich Messages gagal.
    Urutan teks utama dan blok mengikuti `blocks`. Media, musik, dan berkas dikirim terpisah oleh bot."""
    blocks = blocks or []
    body = strip_markers(body_html).strip()
    if spoiler and body:
        body = f"<tg-spoiler>{body}</tg-spoiler>"
    if body and style in ("quote", "details", "aside"):
        body = f"<blockquote>{body}</blockquote>"
    elif body and style == "expand":
        body = "<blockquote expandable>" + body + "</blockquote>"
    head = []
    if title:
        head.append(f"<b>{_esc(title)}</b>")
    if body:
        head.append(body)
    text_part = "\n\n".join(head)
    out = []
    if any(b.get("t") == "@text" for b in blocks):
        for b in blocks:
            if b.get("t") == "@text":
                out.append(text_part)
            elif not b.get("t", "").startswith("@"):
                out.append(plain_block(b))
    else:
        out.append(text_part)
        out.extend(plain_block(b) for b in blocks)
    out = [x for x in out if x]
    if footer:
        out.append(f"<i>{_esc(footer)}</i>")
    return "\n\n".join(out)


# ── Parsing input user ────────────────────────────────────────────────────────

_URL_RE = re.compile(r"^(https?://|tg://)\S+$", re.I)
_HTTP_RE = re.compile(r"^https?://\S+$", re.I)
_USER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")


def _chat_url(v: str) -> str | None:
    v = v.strip()
    m = re.fullmatch(r"@(" + _USER_RE.pattern + ")", v)
    if not m:
        m = re.fullmatch(r"(?:https?://)?t\.me/(" + _USER_RE.pattern + r")/?", v, re.I)
    return f"https://t.me/{m.group(1)}" if m else None


def _parse_one(raw: str, default_type: str | None):
    """Satu tombol: `Teks | nilai | warna`. Return (dict|None, error|None)."""
    parts = [p.strip() for p in raw.split("|")]
    label, rest = parts[0], parts[1:]
    color = ""
    if rest and rest[-1].lower() in BTN_STYLES and (len(rest) >= 2 or default_type == "vote" or rest[-1].lower() == "polos"):
        color = rest.pop().lower()
    value = "|".join(rest).strip()
    m = _PREFIX_RE.match(value)
    if m:
        btype, value = _PREFIX[m.group(1).lower()], m.group(2).strip()
    elif value.lower() == "vote":
        btype, value = "vote", ""
    elif default_type:
        btype = default_type
    elif _URL_RE.match(value):
        btype = "link"
    else:
        return None, ("tidak dikenali. Awali nilai dengan <code>salin:</code>, <code>bagikan:</code>, "
                      "<code>chat:</code>, <code>popup:</code>, atau tulis link https://")
    if not label or len(label) > 64:
        return None, "teks tombol 1 sampai 64 karakter"
    if btype in ("link", "share") and "|" in value:
        return None, "format salah. Warna pilih biru, hijau, merah, atau polos"
    if btype == "link":
        if not _URL_RE.match(value):
            return None, "link harus diawali https://, http://, atau tg://"
    elif btype == "share":
        if not _HTTP_RE.match(value):
            return None, "isi link https:// yang mau dibagikan"
    elif btype == "chat":
        url = _chat_url(value)
        if not url:
            return None, "isi @username atau link t.me/username"
        value = url
    elif btype == "copy":
        if not value or len(value) > 256:
            return None, "teks yang disalin 1 sampai 256 karakter"
    elif btype == "popup":
        if not value or len(value) > 200:
            return None, "teks popup 1 sampai 200 karakter"
    elif btype == "vote":
        value = ""
    return {"type": btype, "label": label, "value": value, "style": BTN_STYLES.get(color, ""), "join": False}, None


def parse_buttons(text: str, default_type: str | None = None) -> tuple[list[dict], list[str]]:
    """Baca tombol. Satu baris = satu baris tombol; pisahkan beberapa tombol sebaris dengan `&&`.

        Teks | https://link
        Salin Kode | salin: PROMO50 && Bagikan | bagikan: https://t.me/channel
        Info | popup: Berlaku sampai Jumat | hijau
        👍 Suka && 👎 Tidak | vote

    default_type (opsional) = jenis bawaan untuk nilai tanpa awalan. Return ([tombol], [error])."""
    buttons: list[dict] = []
    errors: list[str] = []
    for n, raw in enumerate([ln.strip() for ln in (text or "").splitlines() if ln.strip()], 1):
        chunks = [c for c in re.split(r"\s*&&\s*", raw) if c.strip()]
        # `👍 Suka && 👎 Tidak | vote`: potongan tanpa nilai ikut jenis vote bila ada di baris yang sama
        line_vote = default_type == "vote" or any(
            "|" in c and c.split("|", 1)[1].strip().lower().split(":")[0] == "vote" for c in chunks)
        for k, chunk in enumerate(chunks):
            dt = "vote" if (line_vote and "|" not in chunk) else default_type
            b, err = _parse_one(chunk, dt)
            if err:
                errors.append(f"Baris {n}: {err}")
                continue
            b["join"] = k > 0
            buttons.append(b)
    if len(buttons) > MAX_BUTTONS:
        errors.append(f"Maksimal {MAX_BUTTONS} tombol")
        buttons = buttons[:MAX_BUTTONS]
    if sum(1 for b in buttons if b["type"] == "vote") > MAX_VOTES:
        errors.append(f"Maksimal {MAX_VOTES} tombol vote")
    return buttons, errors



def parse_chat_ref(text: str):
    """Ubah teks jadi referensi chat: ID angka (int), '@username', atau None bila tidak dikenali."""
    t = (text or "").strip()
    if re.fullmatch(r"-?\d{5,}", t):
        return int(t)
    m = re.fullmatch(r"(?:https?://)?t\.me/c/(\d+)(?:/\d+)?/?", t, re.I)
    if m:
        return int("-100" + m.group(1))
    m = re.fullmatch(r"(?:https?://)?t\.me/([A-Za-z][A-Za-z0-9_]{3,31})(?:/\d+)?/?", t, re.I)
    if m:
        return "@" + m.group(1)
    m = re.fullmatch(r"@([A-Za-z][A-Za-z0-9_]{3,31})", t)
    if m:
        return "@" + m.group(1)
    return None


def post_link(chat_id: int, username: str | None, message_id: int) -> str | None:
    if username:
        return f"https://t.me/{username}/{message_id}"
    if str(chat_id).startswith("-100"):
        return f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"
    return None




# ── Klien API ─────────────────────────────────────────────────────────────────

async def call_api(token: str, method: str, payload: dict, timeout: float = 30.0) -> dict:
    """POST ke Bot API. Retry sekali untuk 429. Raise RichError bila gagal."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(2):
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
        try:
            data = resp.json()
        except Exception:
            data = {}
        if data.get("ok"):
            return data.get("result") or {}
        params = data.get("parameters") or {}
        retry = params.get("retry_after")
        if resp.status_code == 429 and retry and retry <= 10 and attempt == 0:
            await asyncio.sleep(retry + 0.5)
            continue
        raise RichError(data.get("description") or f"HTTP {resp.status_code}", resp.status_code, retry)
    raise RichError("Gagal menghubungi Telegram")


async def send_rich(token: str, chat_id, html_body: str, *, media: list | None = None,
                    reply_markup: dict | None = None, silent: bool = False, protect: bool = False) -> dict:
    """Kirim Rich Message. `reply_markup` = inline_keyboard dict (tombol di bawah). Return objek Message."""
    if len(html_body) > MAX_RICH_CHARS:
        raise RichError(f"Isi terlalu panjang ({len(html_body)} dari {MAX_RICH_CHARS} karakter)")
    rich: dict = {"html": html_body}
    if media:
        rich["media"] = media
    payload: dict = {"chat_id": chat_id, "rich_message": rich}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if silent:
        payload["disable_notification"] = True
    if protect:
        payload["protect_content"] = True
    return await call_api(token, "sendRichMessage", payload)


async def edit_markup(token: str, chat_id, message_id: int, markup: dict) -> dict:
    """Ganti tombol pesan yang sudah terkirim (dipakai untuk memperbarui hitungan vote)."""
    return await call_api(token, "editMessageReplyMarkup",
                          {"chat_id": chat_id, "message_id": message_id, "reply_markup": markup})


# ── Blok tambahan (daftar, tabel, kode, kutipan, rumus, peta, galeri, musik, berkas, ...) ──

MAX_BLOCKS = 20
MAX_GALLERY = 10
MAX_FILE_MB = 50                    # batas unduh file oleh bot (Bot API: 20 MB untuk getFile; kirim memakai file_id)
BLOCK_INFO = {                      # tipe: (ikon, nama)
    "heading": ("🔤", "Heading"), "list": ("📋", "Daftar"), "table": ("📊", "Tabel"), "code": ("💻", "Kode"),
    "quote": ("💬", "Kutipan"), "pull": ("📌", "Kutipan tengah"), "fold": ("🔽", "Teks lipat"),
    "math": ("➗", "Rumus"), "map": ("📍", "Peta"), "gallery": ("🖼️", "Galeri"),
    "audio": ("🎵", "Musik"), "file": ("📎", "Berkas"),
    "divider": ("➖", "Pemisah"), "btns": ("🔘", "Tombol"),
    "@text": ("📝", "Teks utama"), "@media": ("🖼", "Media utama"),
}
# Kategori untuk menu tambah blok (supaya tombol tidak berantakan)
BLOCK_CATS = {
    "teks": ("📝 Teks", ["heading", "quote", "pull", "fold", "divider"]),
    "data": ("📊 Data", ["list", "table", "code", "math"]),
    "media": ("🖼 Media & File", ["gallery", "audio", "file", "map"]),
    "btn": ("🔘 Tombol", ["btns"]),
}
BLOCK_CAT_ORDER = ["teks", "data", "media", "btn"]
BLOCK_ORDER = [t for c in BLOCK_CAT_ORDER for t in BLOCK_CATS[c][1]]
INSTANT_BLOCKS = ("divider", "btns")                       # langsung ditambah tanpa input
UPLOAD_BLOCKS = ("audio", "file")                          # satu file, tanpa tombol Selesai
CODE_LANGS = [("Python", "python"), ("JavaScript", "javascript"), ("JSON", "json"),
              ("Bash", "bash"), ("HTML", "html"), ("Tanpa bahasa", "-")]
LIST_KINDS = [("• Poin", "ul"), ("1. Nomor", "ol"), ("☑ Centang", "chk")]
HEADING_SIZES = [("H1 besar", "1"), ("H2 sedang", "2"), ("H3 kecil", "3")]
GALLERY_KINDS = [("Kolase", "collage"), ("Slideshow", "slideshow")]
OPTIONS = {"list": LIST_KINDS, "code": CODE_LANGS, "heading": HEADING_SIZES, "gallery": GALLERY_KINDS}


_BULLET_RE = re.compile(r"^(?:[-*\u2022]|\d+[.)])\s+")
_CHECK_RE = re.compile(r"^\[([xX ])?\]\s*(.*)$")
_COORD_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def make_block(t: str, opt: str, text: str, location: tuple | None = None):
    """Ubah input user jadi blok. Return (blok, None) atau (None, pesan_error)."""
    text = (text or "").strip()
    if t == "heading":
        if not text or len(text) > 150:
            return None, "Teks heading 1 sampai 150 karakter."
        return {"t": "heading", "size": int(opt or 2), "text": text}, None
    if t == "list":
        items = []
        for ln in _lines(text):
            checked = False
            if opt == "chk":
                m = _CHECK_RE.match(ln)
                if m:
                    checked, ln = (m.group(1) or "").lower() == "x", m.group(2)
            ln = _BULLET_RE.sub("", ln).strip()
            if ln:
                items.append((ln[:300], checked))
        if not items:
            return None, "Kirim minimal satu item, satu per baris."
        if len(items) > 30:
            return None, "Maksimal 30 item."
        return {"t": "list", "kind": opt or "ul", "items": items}, None
    if t == "table":
        rows = []
        for ln in _lines(text):
            ln = ln.strip("|")
            rows.append([c.strip()[:100] for c in ln.split("|")])
        if len(rows) < 2:
            return None, "Minimal 2 baris: header dan satu baris data."
        if len(rows) > 30:
            return None, "Maksimal 30 baris."
        width = max(len(r) for r in rows)
        if width < 2:
            return None, "Pisahkan kolom dengan tanda <code>|</code>."
        if width > 8:
            return None, "Maksimal 8 kolom agar tetap terbaca di HP."
        return {"t": "table", "rows": [r + [""] * (width - len(r)) for r in rows]}, None
    if t == "code":
        if not text:
            return None, "Kode tidak boleh kosong."
        if len(text) > 3000:
            return None, "Kode maksimal 3000 karakter."
        return {"t": "code", "lang": "" if opt in (None, "", "-") else opt, "code": text}, None
    if t in ("quote", "pull"):
        body, credit = (text.rsplit("|", 1) if "|" in text else (text, ""))
        body, credit = body.strip(), credit.strip()
        if not body or len(body) > 1500 or len(credit) > 100:
            return None, "Teks 1 sampai 1500 karakter, sumber maksimal 100."
        return {"t": t, "text": body, "credit": credit}, None
    if t == "fold":
        ls = text.splitlines()
        title, content = (ls[0].strip() if ls else ""), "\n".join(ls[1:]).strip()
        if not title or not content:
            return None, "Baris pertama = judul, baris berikutnya = isi."
        if len(title) > 100 or len(content) > 3000:
            return None, "Judul maksimal 100 dan isi maksimal 3000 karakter."
        return {"t": "fold", "title": title, "text": content}, None
    if t == "math":
        if not text or len(text) > 500:
            return None, "Rumus LaTeX 1 sampai 500 karakter."
        return {"t": "math", "expr": text}, None
    if t == "map":
        if location:
            lat, lon = location
        else:
            m = _COORD_RE.match(text)
            if not m:
                return None, "Kirim lokasi Telegram, atau ketik <code>-6.2088, 106.8456</code>."
            lat, lon = float(m.group(1)), float(m.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None, "Koordinat di luar jangkauan."
        return {"t": "map", "lat": round(float(lat), 6), "lon": round(float(lon), 6), "zoom": 14}, None
    return None, "Jenis blok tidak dikenal."




def render_block(b: dict, index: int = 0) -> str:
    t = b.get("t")
    if t == "heading":
        n = max(1, min(int(b["size"]), 6))
        return f"<h{n}>{_esc(b['text'])}</h{n}>"
    if t == "list":
        if b["kind"] == "chk":
            return "<ul>" + "".join(f"<li>{'☑' if c else '☐'} {_esc(x)}</li>" for x, c in b["items"]) + "</ul>"
        tag = "ol" if b["kind"] == "ol" else "ul"
        return f"<{tag}>" + "".join(f"<li>{_esc(x)}</li>" for x, _ in b["items"]) + f"</{tag}>"
    if t == "table":
        head, *rest = b["rows"]
        out = "<table bordered striped><tr>" + "".join(f"<th>{_esc(c)}</th>" for c in head) + "</tr>"
        out += "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in rest)
        return out + "</table>"
    if t == "code":
        code = _esc(b["code"])
        lang = f' class="language-{html.escape(b["lang"], quote=True)}"' if b.get("lang") else ""
        return f"<pre><code{lang}>{code}</code></pre>"
    if t in ("quote", "pull"):
        tag = "blockquote" if t == "quote" else "aside"
        cite = f"<cite>{_esc(b['credit'])}</cite>" if b.get("credit") else ""
        return f"<{tag}>{_esc(b['text']).replace(chr(10), '<br/>')}{cite}</{tag}>"
    if t == "fold":
        return f"<details><summary>{_esc(b['title'])}</summary><p>{_esc(b['text']).replace(chr(10), '<br/>')}</p></details>"
    if t == "math":
        return f"<tg-math-block>{_esc(b['expr'])}</tg-math-block>"
    if t == "map":
        return f'<tg-map lat="{b["lat"]}" long="{b["lon"]}" zoom="{b.get("zoom", 14)}"/>'
    if t == "gallery":
        tag = "tg-slideshow" if b["kind"] == "slideshow" else "tg-collage"
        sp = " tg-spoiler" if b.get("spoiler") else ""
        imgs = "".join(f'<img src="tg://photo?id=g{index}x{n}"{sp}/>' for n in range(len(b["files"])))
        return f"<{tag}>{imgs}</{tag}>"
    if t == "audio":
        el = f'<audio src="tg://audio?id=a{index}"></audio>'
        return f"<figure>{el}{_figcaption(b.get('caption', ''))}</figure>" if b.get("caption") else el
    if t == "file":
        el = f'<tg-document src="tg://document?id=d{index}"></tg-document>'
        return f"<figure>{el}{_figcaption(b.get('caption', ''))}</figure>" if b.get("caption") else el
    if t == "divider":
        return "<hr/>"
    return ""


def plain_block(b: dict) -> str:
    """Padanan pesan biasa (HTML Telegram) untuk cadangan. Galeri, musik, dan berkas dikirim terpisah oleh bot."""
    t = b.get("t")
    if t == "heading":
        return f"<b>{_esc(b['text'])}</b>"
    if t == "list":
        if b["kind"] == "ol":
            return "\n".join(f"{n}. {_esc(x)}" for n, (x, _) in enumerate(b["items"], 1))
        if b["kind"] == "chk":
            return "\n".join(f"{'☑' if c else '☐'} {_esc(x)}" for x, c in b["items"])
        return "\n".join(f"• {_esc(x)}" for x, _ in b["items"])
    if t == "table":
        widths = [max(len(r[i]) for r in b["rows"]) for i in range(len(b["rows"][0]))]
        lines = [" | ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in b["rows"]]
        return "<pre>" + _esc("\n".join(lines[:1] + ["-" * len(lines[0])] + lines[1:])) + "</pre>"
    if t == "code":
        lang = f' class="language-{html.escape(b["lang"], quote=True)}"' if b.get("lang") else ""
        return f"<pre><code{lang}>{_esc(b['code'])}</code></pre>"
    if t in ("quote", "pull"):
        cred = f"\n— {_esc(b['credit'])}" if b.get("credit") else ""
        return f"<blockquote>{_esc(b['text'])}{cred}</blockquote>"
    if t == "fold":
        return f"<b>{_esc(b['title'])}</b>\n<blockquote expandable>{_esc(b['text'])}</blockquote>"
    if t == "math":
        return f"<code>{_esc(b['expr'])}</code>"
    if t == "map":
        return f'<a href="https://www.google.com/maps?q={b["lat"]},{b["lon"]}">📍 Lihat di peta</a>'
    if t == "divider":
        return "──────────"
    return ""


def media_list(kind: str | None, file_id: str | None, blocks: list | None) -> list[dict]:
    """Daftar `media` untuk InputRichMessage: media utama (m1), foto galeri (g<blok>x<n>),
    musik (a<blok>), dan berkas (d<blok>)."""
    out: list[dict] = []
    if kind in ("photo", "video") and file_id:
        out.append({"id": "m1", "media": {"type": kind, "media": file_id}})
    for bi, b in enumerate(blocks or []):
        t = b.get("t")
        if t == "gallery":
            out.extend({"id": f"g{bi}x{n}", "media": {"type": "photo", "media": fid}} for n, fid in enumerate(b["files"]))
        elif t == "audio":
            out.append({"id": f"a{bi}", "media": {"type": "voice_note" if b.get("voice") else "audio", "media": b["file_id"]}})
        elif t == "file":
            out.append({"id": f"d{bi}", "media": {"type": "document", "media": b["file_id"]}})
    return out


def extra_blocks(blocks: list | None) -> list:
    """Blok tambahan saja (tanpa entri khusus @text/@media)."""
    return [b for b in (blocks or []) if not b.get("t", "").startswith("@")]


def block_summary(b: dict) -> str:
    """Ringkasan satu baris untuk daftar blok di bot."""
    t = b.get("t"); ico, name = BLOCK_INFO.get(t, ("▫️", t))
    detail = {
        "heading": lambda: b["text"][:24], "list": lambda: f"{len(b['items'])} item", "table": lambda: f"{len(b['rows'])}x{len(b['rows'][0])}",
        "code": lambda: b.get("lang") or "teks", "quote": lambda: b["text"][:24], "pull": lambda: b["text"][:24],
        "fold": lambda: b["title"][:24], "math": lambda: b["expr"][:24], "map": lambda: f"{b['lat']}, {b['lon']}",
        "gallery": lambda: f"{len(b['files'])} foto" + (" 🙈" if b.get("spoiler") else ""),
        "audio": lambda: (b.get("name") or "")[:24], "file": lambda: (b.get("name") or "")[:24],
    }.get(t, lambda: "")()
    return f"{ico} {name}" + (f": {detail}" if detail else "")

