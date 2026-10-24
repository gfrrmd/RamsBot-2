"""
Rich Messages (Bot API 10.1+): klien HTTP + pembangun konten.

python-telegram-bot 21.11.1 belum punya method `sendRichMessage`, jadi dipanggil langsung
lewat HTTP. Modul ini sengaja tidak mengimpor `config` supaya fungsi murninya mudah dites.
"""
import asyncio
import html
import re

import httpx

MAX_RICH_CHARS = 32768       # batas isi Rich Message
MAX_CAPTION = 1024           # batas caption pesan biasa (fallback)
MAX_BUTTONS = 8
MAX_COLS = 3

# Warna tombol (Bot API 10.3). Kosong = warna bawaan aplikasi.
BTN_STYLES = {"biru": "primary", "primary": "primary", "hijau": "success", "success": "success",
              "merah": "danger", "danger": "danger", "polos": "", "default": "", "normal": ""}
ALIGNS = ["left", "center", "right"]
ALIGN_LABEL = {"left": "Kiri", "center": "Tengah", "right": "Kanan"}

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


def _button_tag(b) -> str:
    label, url = b[0], b[1]
    style = b[2] if len(b) > 2 else ""
    st = f' style="{style}"' if style else ""
    return f'<tg-button type="url" url="{html.escape(url, quote=True)}"{st}>{_esc(label)}</tg-button>'


def button_rows(buttons: list, cols: int = 1, align: str = "left") -> str:
    """Tombol dalam teks: satu <tg-button-row> per `cols` tombol (maks 8 per baris)."""
    cols = max(1, min(int(cols or 1), MAX_BUTTONS))
    attr = f' align="{align}"' if align in ("center", "right") else ""
    return "".join(
        f"<tg-button-row{attr}>" + "".join(_button_tag(b) for b in buttons[i:i + cols]) + "</tg-button-row>"
        for i in range(0, len(buttons), cols)
    )


def _segments(body: str, buttons: list, append_rest: bool = True) -> list:
    """Pecah isi di penanda tombol. Return [("text", str) | ("btn", [tombol...])].
    Tombol yang belum ditempatkan oleh penanda mana pun ditaruh di akhir isi (jika append_rest)."""
    pieces = _MARKER_RE.split(body)             # [teks, nomor|None, teks, nomor|None, ..., teks]
    segs, placed = [], set()
    for i in range(0, len(pieces), 2):
        segs.append(("text", pieces[i]))
        if i + 1 < len(pieces):
            n = pieces[i + 1]
            idx = list(range(len(buttons))) if n is None else ([int(n) - 1] if 0 <= int(n) - 1 < len(buttons) else [])
            placed.update(idx)
            if idx:
                segs.append(("btn", [buttons[k] for k in idx]))
    rest = [b for k, b in enumerate(buttons) if k not in placed]
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


def build_rich_html(body_html: str, *, style: str = "normal", title: str = "", spoiler: bool = False,
                    divider: bool = False, footer: str = "", media_kind: str | None = None,
                    media_id: str = "m1", buttons: list | None = None, buttons_inline: bool = False,
                    cols: int = 1, align: str = "left", blocks: list | None = None,
                    title_size: int = 2) -> str:
    """Susun Rich HTML dari isi pesan (HTML ala Telegram), blok tambahan, dan opsi format.

    Tombol hanya masuk ke HTML bila `buttons_inline` True (tombol dalam teks). Bila False, tombol
    dikirim terpisah sebagai inline keyboard biasa dan penanda `{tombol}` dibuang dari isi."""
    buttons = buttons or []
    blocks = blocks or []
    inline = bool(buttons) and buttons_inline
    block_btns = inline and any(b.get("t") == "btns" for b in blocks)   # blok "Tombol" menentukan posisinya sendiri
    body = (body_html or "").strip()
    if not inline:
        body = strip_markers(body).strip()
    segs = _segments(body, buttons, append_rest=not block_btns) if inline else [("text", body)]

    parts: list[str] = []
    if media_kind in ("photo", "video"):
        tag = "img" if media_kind == "photo" else "video"
        sp = " tg-spoiler" if spoiler else ""
        parts.append(f'<figure><{tag} src="tg://{media_kind}?id={media_id}"{sp}/></figure>')
    if title and style != "details":
        size = max(1, min(int(title_size or 2), 6))
        parts.append(f"<h{size}>{_esc(title)}</h{size}>")

    if style == "details":
        inner = []
        for kind, val in segs:
            if kind == "btn":
                inner.append(button_rows(val, cols, align))
            elif val.strip():
                t = _prep(val)
                inner.append(f"<tg-spoiler>{t}</tg-spoiler>" if spoiler else t)
        if inner:
            parts.append(f"<details><summary>{_esc(title) or 'Selengkapnya'}</summary>{''.join(inner)}</details>")
    else:
        for kind, val in segs:
            parts.append(button_rows(val, cols, align) if kind == "btn" else _wrap_text(val, style, spoiler))

    for bi, b in enumerate(blocks):
        if b.get("t") == "btns":
            if inline:
                parts.append(button_rows(buttons, cols, align))
        else:
            parts.append(render_block(b, bi))

    if divider:
        parts.append("<hr/>")
    if footer:
        parts.append(f"<footer>{_esc(footer)}</footer>")
    return "".join(parts)


def build_plain_html(body_html: str, *, style: str = "normal", title: str = "", spoiler: bool = False,
                     footer: str = "", blocks: list | None = None) -> str:
    """Versi pesan biasa (parse_mode=HTML) dipakai sebagai cadangan jika Rich Messages gagal."""
    body = strip_markers(body_html).strip()
    if spoiler and body:
        body = f"<tg-spoiler>{body}</tg-spoiler>"
    if body and style in ("quote", "details", "aside"):
        body = f"<blockquote>{body}</blockquote>"
    elif body and style == "expand":
        body = "<blockquote expandable>" + body + "</blockquote>"
    out = []
    if title:
        out.append(f"<b>{_esc(title)}</b>")
    if body:
        out.append(body)
    out.extend(x for x in (plain_block(bk) for bk in (blocks or [])) if x)
    if footer:
        out.append(f"<i>{_esc(footer)}</i>")
    return "\n\n".join(out)


# ── Parsing input user ────────────────────────────────────────────────────────

_URL_RE = re.compile(r"^(https?://|tg://)\S+$", re.I)


def parse_buttons(text: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Baca baris `Teks | https://link` atau `Teks | https://link | warna`.
    Return ([(teks, url, style)], [error]). Warna: biru, hijau, merah, polos."""
    buttons: list[tuple[str, str, str]] = []
    errors: list[str] = []
    for n, raw in enumerate([ln.strip() for ln in (text or "").splitlines() if ln.strip()], 1):
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) not in (2, 3):
            errors.append(f"Baris {n}: pakai format <code>Teks | https://link</code> atau <code>Teks | https://link | warna</code>")
            continue
        label, url = parts[0], parts[1]
        color = parts[2].lower() if len(parts) == 3 else ""
        if not label or len(label) > 64:
            errors.append(f"Baris {n}: teks tombol 1 sampai 64 karakter")
        elif not _URL_RE.match(url):
            errors.append(f"Baris {n}: link harus diawali https://, http://, atau tg://")
        elif color not in BTN_STYLES and color != "":
            errors.append(f"Baris {n}: warna pilih biru, hijau, merah, atau polos")
        else:
            buttons.append((label, url, BTN_STYLES.get(color, "")))
    if len(buttons) > MAX_BUTTONS:
        errors.append(f"Maksimal {MAX_BUTTONS} tombol")
        buttons = buttons[:MAX_BUTTONS]
    return buttons, errors


def buttons_markup(buttons: list) -> dict | None:
    """inline_keyboard biasa dalam bentuk dict JSON (satu tombol per baris)."""
    if not buttons:
        return None
    rows = []
    for b in buttons:
        item = {"text": b[0], "url": b[1]}
        if len(b) > 2 and b[2]:
            item["style"] = b[2]
        rows.append([item])
    return {"inline_keyboard": rows}


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
                    buttons: list | None = None, silent: bool = False, protect: bool = False) -> dict:
    """Kirim Rich Message. Return objek Message dari Telegram."""
    if len(html_body) > MAX_RICH_CHARS:
        raise RichError(f"Isi terlalu panjang ({len(html_body)} dari {MAX_RICH_CHARS} karakter)")
    rich: dict = {"html": html_body}
    if media:
        rich["media"] = media
    payload: dict = {"chat_id": chat_id, "rich_message": rich}
    markup = buttons_markup(buttons or [])
    if markup:
        payload["reply_markup"] = markup
    if silent:
        payload["disable_notification"] = True
    if protect:
        payload["protect_content"] = True
    return await call_api(token, "sendRichMessage", payload)


# ── Blok tambahan (daftar, tabel, kode, kutipan, rumus, peta, galeri, ...) ───────────────────

MAX_BLOCKS = 20
MAX_GALLERY = 10
BLOCK_INFO = {                      # tipe: (ikon, nama)
    "heading": ("🔤", "Heading"), "list": ("📋", "Daftar"), "table": ("📊", "Tabel"), "code": ("💻", "Kode"),
    "quote": ("💬", "Kutipan"), "pull": ("📌", "Kutipan tengah"), "fold": ("🔽", "Teks lipat"),
    "math": ("➗", "Rumus"), "map": ("📍", "Peta"), "gallery": ("🖼️", "Galeri"),
    "divider": ("➖", "Pemisah"), "btns": ("🔘", "Tombol"),
}
BLOCK_ORDER = ["heading", "list", "table", "code", "quote", "pull", "fold", "math", "map", "gallery", "divider", "btns"]
INSTANT_BLOCKS = ("divider", "btns")                       # langsung ditambah tanpa input
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
        imgs = "".join(f'<img src="tg://photo?id=g{index}x{n}"/>' for n in range(len(b["files"])))
        return f"<{tag}>{imgs}</{tag}>"
    if t == "divider":
        return "<hr/>"
    return ""


def plain_block(b: dict) -> str:
    """Padanan pesan biasa (HTML Telegram) untuk cadangan. Galeri tidak ikut terkirim."""
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
    """Daftar `media` untuk InputRichMessage: media utama (id m1) dan foto galeri (id g<blok>x<n>)."""
    out: list[dict] = []
    if kind in ("photo", "video") and file_id:
        out.append({"id": "m1", "media": {"type": kind, "media": file_id}})
    for bi, b in enumerate(blocks or []):
        if b.get("t") == "gallery":
            out.extend({"id": f"g{bi}x{n}", "media": {"type": "photo", "media": fid}} for n, fid in enumerate(b["files"]))
    return out


def block_summary(b: dict) -> str:
    """Ringkasan satu baris untuk daftar blok di bot."""
    t = b.get("t"); ico, name = BLOCK_INFO.get(t, ("▫️", t))
    detail = {
        "heading": lambda: b["text"][:24], "list": lambda: f"{len(b['items'])} item", "table": lambda: f"{len(b['rows'])}x{len(b['rows'][0])}",
        "code": lambda: b.get("lang") or "teks", "quote": lambda: b["text"][:24], "pull": lambda: b["text"][:24],
        "fold": lambda: b["title"][:24], "math": lambda: b["expr"][:24], "map": lambda: f"{b['lat']}, {b['lon']}",
        "gallery": lambda: f"{len(b['files'])} foto",
    }.get(t, lambda: "")()
    return f"{ico} {name}" + (f": {detail}" if detail else "")
