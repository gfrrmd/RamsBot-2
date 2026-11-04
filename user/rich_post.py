"""
Fitur VIP: Rich Post. Posting ke channel/grup memakai Rich Messages (Bot API 10.1+).

Alur (semua di chat dengan bot, tanpa session Telethon):
  1. Tambahkan bot sebagai admin di channel/grup tujuan, lalu daftarkan tujuannya di bot.
  2. Kirim isi postingan (teks, atau foto/video + caption).
  3. Atur lewat kategori: 🎨 Tampilan, 🧱 Blok & Urutan, 🔘 Tombol, ⚙️ Pengiriman.
  4. Pratinjau, pilih tujuan, Posting.

Tombol: Link, Salin, Bagikan, Chat, Popup, Vote; bisa beberapa per baris. Blok: daftar, tabel, kode, kutipan,
rumus, peta, galeri (dengan spoiler), musik, berkas. Teks utama dan media utama bisa dipindah posisinya.

Keamanan: bot hanya memposting jika bot DAN pengguna sama-sama admin di tujuan tersebut.
Jika Rich Messages ditolak Telegram, posting tidak dikirim otomatis. Pengguna ditawari
kirim sebagai pesan biasa (HTML) lewat tombol terpisah.
"""
import json

from telegram import (CallbackQuery, CopyTextButton, InlineKeyboardButton as Btn, InlineKeyboardMarkup,
                      InputMediaPhoto, Update)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from auth.states import clear_input_waits, rich_draft, rich_wait
from config import BOT_TOKEN
from database import (add_rich_target, delete_rich_target, get_rich_targets, is_subscribed, rich_poll_kb,
                      rich_poll_new, rich_poll_set_kb, rich_popup_id, rich_popup_text, rich_vote_toggle)
from ui import edit_or_send, esc, header_e as header
from utils.rich import (
    ALIGN_LABEL, ALIGNS, BLOCK_CAT_ORDER, BLOCK_CATS, BLOCK_INFO, BTN_HELP, BTN_ORDER, BTN_TYPES,
    INSTANT_BLOCKS, MAX_BLOCKS, MAX_BUTTONS, MAX_CAPTION, MAX_GALLERY, MAX_RICH_CHARS, MAX_VOTES, OPTIONS,
    STYLE_LABEL, STYLES, UPLOAD_BLOCKS, RichError,
    block_summary, build_plain_html, build_rich_html, buttons_summary, clean_markup, edit_markup, extra_blocks,
    inline_markup, make_block, media_list, parse_buttons, parse_chat_ref, post_link, rows_of, send_rich,
    split_buttons,
)

_BUY_KB = InlineKeyboardMarkup([[Btn("💎 Beli / Perpanjang VIP", callback_data="pay_menu")],
                                [Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")]])
_BACK_RICH = InlineKeyboardMarkup([[Btn("🔙 Menu Rich Post", callback_data="fitur_rich")]])
_BACK_PANEL = InlineKeyboardMarkup([[Btn("🔙 Kembali ke opsi", callback_data="rp_panel")]])
_BACK_LOOK = InlineKeyboardMarkup([[Btn("🔙 Tampilan", callback_data="rp_look")]])
_BACK_BTN = InlineKeyboardMarkup([[Btn("🔙 Tombol", callback_data="rp_buttons")]])


# ── Draf ──────────────────────────────────────────────────────────────────────

def _new_draft() -> dict:
    return {"kind": None, "file_id": None, "body": "", "style": "normal", "title": "", "spoiler": False,
            "divider": False, "footer": "", "buttons": [], "btn_pos": "bottom", "align": "left",
            "blocks": [{"t": "@text"}], "title_size": 2, "_pend": None, "_btype": None, "_breplace": False,
            "silent": False, "protect": False}


def _sync_main(d: dict) -> None:
    """Pastikan entri khusus ada: satu @text, dan @media hanya bila ada foto/video utama."""
    blocks = d["blocks"]
    if not any(b["t"] == "@text" for b in blocks):
        blocks.append({"t": "@text"})
    has_media = any(b["t"] == "@media" for b in blocks)
    if d["kind"] in ("photo", "video") and not has_media:
        blocks.insert(0, {"t": "@media"})
    elif d["kind"] not in ("photo", "video") and has_media:
        d["blocks"] = [b for b in blocks if b["t"] != "@media"]


def _onoff(v: bool) -> str:
    return "ON ✅" if v else "OFF"


def _content_label(d: dict) -> str:
    n = len(d["body"])
    return {"photo": f"Foto + caption ({n} karakter)", "video": f"Video + caption ({n} karakter)"}.get(
        d["kind"], f"Teks ({n} karakter)")


def _btn_label(d: dict) -> str:
    if not d["buttons"]:
        return "0"
    return f"{len(d['buttons'])} ({'dalam teks' if d['btn_pos'] == 'inline' else 'di bawah'})"


def _panel_text(d: dict) -> str:
    order = "→".join(BLOCK_INFO[b["t"]][0] for b in d["blocks"]) if len(d["blocks"]) > 1 else ""
    return (
        f"{header('📰', 'Rich Post')}\n"
        f"<b>Isi:</b> {esc(_content_label(d))}\n"
        f"<b>Gaya:</b> {STYLE_LABEL[d['style']]}   <b>Judul:</b> {esc(d['title']) if d['title'] else '—'}\n"
        f"<b>Blok tambahan:</b> {len(extra_blocks(d['blocks']))}   <b>Tombol:</b> {_btn_label(d)}\n"
        + (f"<b>Urutan:</b> {order}\n" if order else "")
        + "\nPilih kategori di bawah, cek <b>Pratinjau</b>, lalu pilih tujuan."
    )


def _panel_kb(d: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [Btn("🎨 Tampilan", callback_data="rp_look"),
         Btn(f"🧱 Blok & Urutan ({len(extra_blocks(d['blocks']))})", callback_data="rp_blocks")],
        [Btn(f"🔘 Tombol ({len(d['buttons'])})", callback_data="rp_buttons"),
         Btn("⚙️ Pengiriman", callback_data="rp_send")],
        [Btn("👁️ Pratinjau", callback_data="rp_preview"), Btn("📤 Pilih Tujuan", callback_data="rp_targets")],
        [Btn("✏️ Ganti Isi", callback_data="rp_content"), Btn("❌ Batal", callback_data="rp_cancel")],
    ])


async def _panel(target, d: dict, *, fresh: bool = False):
    """Tampilkan panel. `target` = CallbackQuery (edit) atau Message (kirim baru)."""
    text, kb = _panel_text(d), _panel_kb(d)
    if isinstance(target, CallbackQuery) and not fresh:
        await edit_or_send(target, text, kb)
    else:
        msg = target.message if isinstance(target, CallbackQuery) else target
        await msg.chat.send_message(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def _reply(target, text: str, kb=None):
    """Edit pesan jika dari tombol, kirim baru jika dari pesan."""
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, kb)
    else:
        await target.chat.send_message(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def _look_screen(target, d: dict):
    d["_pend"] = None
    rows = [
        [Btn(f"🎨 Gaya: {STYLE_LABEL[d['style']]}", callback_data="rp_style")],
        [Btn(f"🙈 Spoiler: {_onoff(d['spoiler'])}", callback_data="rp_spoiler"),
         Btn(f"➖ Pemisah: {_onoff(d['divider'])}", callback_data="rp_divider")],
        [Btn("🔤 Judul", callback_data="rp_title"), Btn("📝 Footer", callback_data="rp_footer")],
    ]
    if d["title"] and d["style"] != "details":
        rows.append([Btn(f"🔠 Ukuran judul: H{d['title_size']}", callback_data="rp_tsize")])
    rows.append([Btn("🔙 Kembali ke opsi", callback_data="rp_panel")])
    await _reply(target, (
        f"{header('🎨', 'Tampilan')}\n"
        f"<b>Gaya:</b> {STYLE_LABEL[d['style']]}\n"
        f"<b>Judul:</b> {esc(d['title']) if d['title'] else '—'}\n"
        f"<b>Footer:</b> {esc(d['footer']) if d['footer'] else '—'}\n\n"
        "🙈 Spoiler menutupi teks dan foto/video utama. Untuk galeri, spoiler diatur di menu 🧱 Blok."),
        InlineKeyboardMarkup(rows))


async def _send_screen(target, d: dict):
    await _reply(target, (
        f"{header('⚙️', 'Pengiriman')}\n"
        "🔕 <b>Senyap</b>: terkirim tanpa notifikasi.\n"
        "🛡️ <b>Lindungi</b>: isi tidak bisa di-forward atau disimpan."),
        InlineKeyboardMarkup([
            [Btn(f"🔕 Senyap: {_onoff(d['silent'])}", callback_data="rp_silent")],
            [Btn(f"🛡️ Lindungi: {_onoff(d['protect'])}", callback_data="rp_protect")],
            [Btn("🔙 Kembali ke opsi", callback_data="rp_panel")]]))


# ── Pembuatan konten dan pengiriman ───────────────────────────────────────────

def _alloc(uid: int, d: dict, *, preview: bool = False, force_below: bool = False):
    """Siapkan callback_data tombol popup/vote dan markup 'di bawah'. Return (cb, markup_siap_kirim|None)."""
    inline = d["btn_pos"] == "inline" and not force_below
    intext, below = split_buttons(d["buttons"], inline)
    cb: dict = {}
    for b in intext + below:
        if b["type"] == "popup":
            cb[b["_i"]] = f"rpp:{0 if preview else rich_popup_id(uid, b['value'])}"
    votes = [b for b in below if b["type"] == "vote"]
    pid = 0
    if votes:
        pid = 0 if preview else rich_poll_new(uid)
        for k, b in enumerate(votes):
            cb[b["_i"]] = f"rpv:{pid}:{k}"
    stored = inline_markup(below, cb, meta=True)
    if votes and not preview and stored:
        rich_poll_set_kb(pid, json.dumps(stored))
    return cb, (clean_markup(stored) if stored else None)


def _rich_html(d: dict, cb: dict | None = None) -> str:
    return build_rich_html(d["body"], style=d["style"], title=d["title"], spoiler=d["spoiler"],
                           divider=d["divider"], footer=d["footer"], media_kind=d["kind"],
                           buttons=d["buttons"], buttons_inline=d["btn_pos"] == "inline",
                           align=d["align"], blocks=d["blocks"], title_size=d["title_size"], cb=cb)


async def _send_rich(uid: int, chat_id, d: dict, *, preview: bool = False):
    cb, markup = _alloc(uid, d, preview=preview)
    return await send_rich(BOT_TOKEN, chat_id, _rich_html(d, cb), media=media_list(d["kind"], d["file_id"], d["blocks"]),
                           reply_markup=markup, silent=d["silent"], protect=d["protect"])


def _ptb_markup(markup: dict | None):
    """Dict inline_keyboard -> InlineKeyboardMarkup python-telegram-bot (untuk pesan biasa)."""
    if not markup:
        return None
    rows = []
    for row in markup["inline_keyboard"]:
        r = []
        for it in row:
            if "copy_text" in it:
                r.append(Btn(it["text"], copy_text=CopyTextButton(text=it["copy_text"]["text"])))
            elif "callback_data" in it:
                r.append(Btn(it["text"], callback_data=it["callback_data"]))
            else:
                r.append(Btn(it["text"], url=it["url"]))
        rows.append(r)
    return InlineKeyboardMarkup(rows)


async def _send_plain(bot, uid: int, chat_id, d: dict):
    """Cadangan: pesan biasa (HTML). Musik, berkas, dan galeri dikirim sebagai pesan terpisah."""
    text = build_plain_html(d["body"], style=d["style"], title=d["title"], spoiler=d["spoiler"],
                            footer=d["footer"], blocks=d["blocks"])
    _, markup = _alloc(uid, d, force_below=True)
    mk = _ptb_markup(markup)
    quiet = dict(disable_notification=d["silent"], protect_content=d["protect"])
    sent = None
    if d["kind"] in ("photo", "video"):
        send = bot.send_photo if d["kind"] == "photo" else bot.send_video
        if len(text) <= MAX_CAPTION:
            sent = await send(chat_id, d["file_id"], caption=text or None, parse_mode=ParseMode.HTML,
                              has_spoiler=bool(d["spoiler"]), reply_markup=mk, **quiet)
        else:
            await send(chat_id, d["file_id"], has_spoiler=bool(d["spoiler"]), **quiet)
            sent = await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=mk, **quiet)
    elif text:
        sent = await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML,
                                      disable_web_page_preview=True, reply_markup=mk, **quiet)
    elif mk:
        sent = await bot.send_message(chat_id, "👇", reply_markup=mk, **quiet)
    for b in d["blocks"]:
        t = b["t"]
        if t == "audio":
            m = await (bot.send_voice if b.get("voice") else bot.send_audio)(
                chat_id, b["file_id"], caption=b.get("caption") or None, **quiet)
        elif t == "file":
            m = await bot.send_document(chat_id, b["file_id"], caption=b.get("caption") or None, **quiet)
        elif t == "gallery":
            ms = await bot.send_media_group(
                chat_id, [InputMediaPhoto(f, has_spoiler=bool(b.get("spoiler"))) for f in b["files"]], **quiet)
            m = ms[0] if ms else None
        else:
            continue
        sent = sent or m
    return sent


# ── Validasi tujuan ───────────────────────────────────────────────────────────

async def _check_target(bot, chat_ref, uid: int):
    """Return (chat, None) bila boleh diposting, atau (None, pesan_error_html)."""
    try:
        chat = await bot.get_chat(chat_ref)
    except TelegramError:
        return None, ("❌ Bot tidak bisa menemukan chat itu. Pastikan bot sudah ditambahkan sebagai <b>admin</b> "
                      "di sana, lalu coba lagi. Untuk chat privat, kirim ID angkanya atau forward satu pesan dari chat itu.")
    if chat.type not in ("channel", "group", "supergroup"):
        return None, "❌ Tujuan harus berupa channel atau grup."
    try:
        bot_m = await bot.get_chat_member(chat.id, bot.id)
        usr_m = await bot.get_chat_member(chat.id, uid)
    except TelegramError:
        return None, "❌ Gagal membaca status admin. Pastikan bot adalah <b>admin</b> di chat tersebut."
    if bot_m.status != "administrator":
        return None, f"❌ Bot belum menjadi <b>admin</b> di <b>{esc(chat.title)}</b>. Jadikan @{esc(bot.username)} admin dulu."
    if chat.type == "channel" and getattr(bot_m, "can_post_messages", False) is not True:
        return None, "❌ Bot tidak punya izin <b>Post Messages</b> di channel itu. Aktifkan di pengaturan admin channel."
    if usr_m.status not in ("creator", "administrator"):
        return None, "❌ Kamu harus menjadi <b>admin</b> di chat tujuan untuk memposting ke sana."
    if chat.type == "channel" and usr_m.status == "administrator" and getattr(usr_m, "can_post_messages", None) is False:
        return None, "❌ Akunmu tidak punya izin memposting di channel itu."
    return chat, None


def _targets_kb(uid: int, *, manage: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for t in get_rich_targets(uid):
        icon = "📣" if t["chat_type"] == "channel" else "👥"
        if manage:
            rows.append([Btn(f"{icon} {t['title'][:28]}", callback_data="rp_noop"),
                         Btn("🗑️", callback_data=f"rp_del:{t['chat_id']}")])
        else:
            rows.append([Btn(f"{icon} {t['title'][:40]}", callback_data=f"rp_t:{t['chat_id']}")])
    rows.append([Btn("➕ Tambah Tujuan", callback_data="rp_add")])
    rows.append([Btn("🔙 Kembali", callback_data="rp_panel" if not manage else "fitur_rich")])
    return InlineKeyboardMarkup(rows)


# ── Blok tambahan dan urutan ──────────────────────────────────────────────────

_BLOCK_PROMPTS = {
    "table": "Kirim tabel: satu baris per baris, kolom dipisah <code>|</code>. Baris pertama menjadi header.\n\n"
             "<code>Paket | Harga\nMingguan | 20rb\nBulanan | 50rb</code>",
    "quote": "Kirim teks kutipan. Sumber (opsional) ditulis setelah <code>|</code>.\n\n<code>Belajar tanpa henti | Budi</code>",
    "pull": "Kirim teks kutipan tengah. Sumber (opsional) ditulis setelah <code>|</code>.\n\n<code>Kualitas nomor satu | Redaksi</code>",
    "fold": "Baris pertama = judul yang selalu terlihat. Baris berikutnya = isi yang bisa dibuka.\n\n<code>Syarat\nMinimal 18 tahun\nBawa KTP</code>",
    "math": "Kirim rumus dalam format LaTeX.\n\n<code>E = mc^2</code>",
    "map": "Kirim <b>lokasi Telegram</b> (📎 lalu Lokasi), atau ketik koordinat.\n\n<code>-6.2088, 106.8456</code>",
    "audio": "Kirim <b>file musik</b> (MP3, M4A, dll) sebagai <b>Audio</b>, atau <b>pesan suara</b>.\n"
             "Caption pesan menjadi keterangan di bawah pemutar (opsional).",
    "file": "Kirim <b>berkas apa saja</b> (PDF, ZIP, DOCX, APK, dll) sebagai <b>File/Dokumen</b>.\n"
            "Caption pesan menjadi keterangan di bawah berkas (opsional).",
}


def _block_prompt(t: str, opt: str | None) -> str:
    if t == "list":
        extra = "\nAwali baris dengan <code>[x]</code> untuk item yang sudah dicentang." if opt == "chk" else ""
        return f"Kirim item daftar, <b>satu per baris</b>.{extra}\n\n<code>Diskon 20%\nGratis ongkir\nBonus stiker</code>"
    if t == "code":
        return "Kirim kodenya (maks 3000 karakter)."
    if t == "heading":
        return "Kirim teks heading untuk bagian ini."
    if t == "gallery":
        return f"Kirim <b>2 sampai {MAX_GALLERY} foto</b> satu per satu, lalu tekan <b>Selesai</b>."
    return _BLOCK_PROMPTS.get(t, "")


_BLK_CANCEL = InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="rp_blocks")]])


def _gallery_kb(pend: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [Btn(f"🙈 Spoiler: {_onoff(bool(pend.get('spoiler')))}", callback_data="rp_bgsp")],
        [Btn("✅ Selesai", callback_data="rp_bdone")],
        [Btn("❌ Batal", callback_data="rp_blocks")]])


async def _blocks_screen(target, d: dict, notice: str = ""):
    """Susunan isi dari atas ke bawah, termasuk Teks utama dan Media utama yang bisa dipindah."""
    d["_pend"] = None
    blocks = d["blocks"]
    lines = [f"{n}. {esc(block_summary(b))}" for n, b in enumerate(blocks, 1)]
    text = (f"{header('🧱', 'Blok & Urutan')}\n{notice + chr(10) + chr(10) if notice else ''}"
            "Susunan isi, dari atas ke bawah:\n" + "\n".join(lines) + "\n\n"
            "⬆️ ⬇️ memindah posisi, 🗑 menghapus. <b>Teks utama</b> dan <b>Media utama</b> juga bisa dipindah, "
            "misalnya taruh tabel di atas teks, atau media di paling bawah.")
    rows = []
    last = len(blocks) - 1
    for i, b in enumerate(blocks):
        ico, name = BLOCK_INFO[b["t"]]
        row = [Btn(f"{i + 1}. {ico} {name}"[:18], callback_data="rp_noop")]
        if b["t"] == "gallery":
            row.append(Btn("🙈✓" if b.get("spoiler") else "🙈", callback_data=f"rp_bspoil:{i}"))
        row.append(Btn("⬆️", callback_data=f"rp_bup:{i}") if i > 0 else Btn("·", callback_data="rp_noop"))
        row.append(Btn("⬇️", callback_data=f"rp_bdn:{i}") if i < last else Btn("·", callback_data="rp_noop"))
        if not b["t"].startswith("@"):
            row.append(Btn("🗑", callback_data=f"rp_bdel:{i}"))
        rows.append(row)
    rows.append([Btn("➕ Tambah Blok", callback_data="rp_badd_menu")])
    rows.append([Btn("🔙 Kembali ke opsi", callback_data="rp_panel")])
    await _reply(target, text, InlineKeyboardMarkup(rows))


async def _badd_menu(target, d: dict, notice: str = ""):
    rows = [[Btn(BLOCK_CATS[k][0], callback_data=f"rp_bcat:{k}") for k in BLOCK_CAT_ORDER[i:i + 2]]
            for i in range(0, len(BLOCK_CAT_ORDER), 2)]
    rows.append([Btn("🔙 Susunan", callback_data="rp_blocks")])
    await _reply(target, (
        f"{header('➕', 'Tambah Blok')}\n{notice + chr(10) + chr(10) if notice else ''}"
        "Pilih kategori:\n"
        "📝 <b>Teks</b>: heading, kutipan, teks lipat, pemisah\n"
        "📊 <b>Data</b>: daftar, tabel, kode, rumus\n"
        "🖼 <b>Media & File</b>: galeri, musik, berkas, peta\n"
        "🔘 <b>Tombol</b>: taruh tombol tepat di posisi tertentu"), InlineKeyboardMarkup(rows))


async def _bcat_screen(target, key: str):
    label, types = BLOCK_CATS[key]
    btns = [Btn(f"{BLOCK_INFO[t][0]} {BLOCK_INFO[t][1]}", callback_data=f"rp_badd:{t}") for t in types]
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)]
    rows.append([Btn("🔙 Kategori", callback_data="rp_badd_menu")])
    await _reply(target, f"{header(label.split(' ', 1)[0], label.split(' ', 1)[1])}\nPilih blok yang mau ditambahkan:",
                 InlineKeyboardMarkup(rows))


def _ask_block(uid: int, d: dict, t: str, opt: str | None):
    d["_pend"] = {"t": t, "opt": opt, "files": [], "spoiler": False}
    rich_wait[uid] = "blk"


# ── Tombol ────────────────────────────────────────────────────────────────────

async def _buttons_screen(target, d: dict, notice: str = ""):
    d["_pend"] = None
    d["_btype"], d["_breplace"] = None, False
    inline = d["btn_pos"] == "inline"
    summary = buttons_summary(d["buttons"]) or "Belum ada tombol."
    n_btn = len(d["buttons"])
    legend = "\n".join(f"{BTN_TYPES[t][0]} <b>{BTN_TYPES[t][1]}</b>: {esc(BTN_HELP[t][0])}" for t in BTN_ORDER)
    note = ("\nℹ️ Mode Dalam teks: tombol <b>Salin</b> dan <b>Vote</b> tetap tampil di bawah pesan."
            if inline and any(b["type"] in ("copy", "vote") for b in d["buttons"]) else "")
    rows = [[Btn(f"{BTN_TYPES[t][0]} {BTN_TYPES[t][1]}", callback_data=f"rp_btadd:{t}") for t in BTN_ORDER[i:i + 2]]
            for i in range(0, len(BTN_ORDER), 2)]
    rows.append([Btn("🧩 Atur Baris", callback_data="rp_btlay"), Btn("✍️ Tulis Sekaligus", callback_data="rp_btmanual")])
    rows.append([Btn(f"📍 Posisi: {'Dalam teks' if inline else 'Di bawah'}", callback_data="rp_btnpos"),
                 *([Btn(f"↔️ Rata: {ALIGN_LABEL[d['align']]}", callback_data="rp_align")] if inline else [])])
    rows.append([Btn("🧹 Hapus Semua", callback_data="rp_btclear"), Btn("🔙 Kembali ke opsi", callback_data="rp_panel")])
    await _reply(target, (
        f"{header('🔘', 'Tombol (' + str(n_btn) + ')')}\n"
        f"{notice + chr(10) + chr(10) if notice else ''}{summary}\n\n"
        f"Tambah tombol, pilih jenisnya:\n{legend}{note}"), InlineKeyboardMarkup(rows))


def _btn_prompt(btype: str | None) -> str:
    common = ("\n\n• Satu baris = satu baris tombol.\n"
              "• Beberapa tombol <b>sebaris</b>: pisahkan dengan <code>&amp;&amp;</code>.\n"
              "• Warna (opsional) di akhir: <code>| biru</code>, <code>| hijau</code>, <code>| merah</code>, <code>| polos</code>.")
    if btype is None:
        return ("Kirim banyak tombol sekaligus (<b>menggantikan</b> semua tombol sekarang). Nilai diawali jenisnya:\n\n"
                "<code>Beli Sekarang | https://contoh.com | hijau\n"
                "Salin Kode | salin: PROMO50 &amp;&amp; Bagikan | bagikan: https://t.me/channel\n"
                "Info | popup: Berlaku sampai Jumat\n"
                "Admin | chat: @username\n"
                "👍 Suka &amp;&amp; 👎 Tidak | vote</code>" + common)
    ico, name = BTN_TYPES[btype]
    ex = BTN_HELP[btype][1].replace("&", "&amp;")
    two = {"link": "Web | https://a.com &amp;&amp; Blog | https://b.com",
           "copy": "Kode | PROMO50 &amp;&amp; Rekening | 1234567890",
           "share": "Bagikan | https://t.me/channel &amp;&amp; Ajak Teman | https://t.me/channel",
           "chat": "Admin | @adminku &amp;&amp; CS | @cs_toko",
           "popup": "Syarat | Min. belanja 50rb &amp;&amp; Info | Stok terbatas",
           "vote": "👍 Suka &amp;&amp; 👎 Tidak"}[btype]
    return (f"{BTN_HELP[btype][0]}.\n\nContoh:\n<code>{esc(ex)}</code>\n\nDua tombol sebaris:\n<code>{two}</code>" + common
            + f"\n\nMaksimal {MAX_BUTTONS} tombol"
            + (f", vote maksimal {MAX_VOTES}." if btype == "vote" else "."))


async def _layout_screen(target, d: dict, notice: str = ""):
    d["_pend"] = None
    btns = d["buttons"]
    if not btns:
        await _buttons_screen(target, d, "⚠️ Belum ada tombol untuk diatur.")
        return
    rows = []
    for i, b in enumerate(btns):
        ico = BTN_TYPES[b["type"]][0]
        row = [Btn(f"{i + 1}. {ico} {b['label']}"[:16], callback_data="rp_noop"),
               Btn("⬆️", callback_data=f"rp_xup:{i}") if i else Btn("·", callback_data="rp_noop"),
               (Btn("↔️", callback_data=f"rp_xjoin:{i}") if b.get("join") else Btn("⤵️", callback_data=f"rp_xjoin:{i}"))
               if i else Btn("·", callback_data="rp_noop"),
               Btn("🗑", callback_data=f"rp_xdel:{i}")]
        rows.append(row)
    rows.append([Btn("1 per baris", callback_data="rp_xcols:1"), Btn("2 per baris", callback_data="rp_xcols:2"),
                 Btn("3 per baris", callback_data="rp_xcols:3")])
    rows.append([Btn("🔙 Tombol", callback_data="rp_buttons")])
    await _reply(target, (
        f"{header('🧩', 'Atur Baris')}\n{notice + chr(10) + chr(10) if notice else ''}"
        f"{buttons_summary(btns)}\n\n"
        "⬆️ naikkan tombol • ↔️ sebaris dengan tombol di atasnya (tap untuk memisah) • "
        "⤵️ baris baru (tap untuk digabung ke baris atas) • 🗑 hapus.\n"
        "Pintasan: <b>1/2/3 per baris</b> menyusun semua tombol otomatis. Maksimal 8 tombol per baris."),
        InlineKeyboardMarkup(rows))


# ── Callback ──────────────────────────────────────────────────────────────────

_INTRO = (
    "Posting ke channel atau grup dengan format Rich Messages: judul, kutipan, teks lipat, spoiler, footer, "
    "tombol (link, salin, bagikan, chat, popup, vote), plus blok <b>daftar, tabel, kode, rumus, peta, galeri, "
    "musik, berkas</b>. Posisi teks dan media bisa dipindah. Semua lewat tombol. <b>Tidak perlu setup session.</b>\n\n"
    "📝 <b>Cara pakai:</b>\n"
    "<b>1.</b> Jadikan @{bot} <b>admin</b> di channel/grup tujuan (di channel, aktifkan izin Post Messages).\n"
    "<b>2.</b> Tekan <b>Tujuan Saya</b>, lalu <b>Tambah Tujuan</b>.\n"
    "<b>3.</b> Tekan <b>Buat Postingan</b>, kirim teks, atau foto/video dengan caption.\n"
    "<b>4.</b> Atur lewat kategori <b>Tampilan</b>, <b>Blok & Urutan</b>, <b>Tombol</b>, cek pratinjau, pilih tujuan, lalu posting.\n\n"
    "ℹ️ Kamu juga harus admin di tujuan tersebut. Rich Messages tampil sempurna di Telegram versi terbaru."
)


async def rich_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()

    if not is_subscribed(uid):
        rich_wait.pop(uid, None)
        await edit_or_send(query, f"{header('📰', 'Rich Post')}\nFitur ini khusus <b>user VIP</b>. "
                                  "Beli atau perpanjang VIP untuk memakainya.", _BUY_KB)
        return
    if data == "rp_noop":
        return

    if data == "fitur_rich":
        clear_input_waits(uid)
        await edit_or_send(
            query, f"{header('📰', 'Rich Post')}\n" + _INTRO.replace("{bot}", esc(context.bot.username)),
            InlineKeyboardMarkup([
                [Btn("📝 Buat Postingan", callback_data="rp_new")],
                [Btn("📍 Tujuan Saya", callback_data="rp_mine")],
                [Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")],
            ]),
        )
        return

    if data == "rp_new":
        rich_draft[uid] = _new_draft()
        rich_wait[uid] = "content"
        await edit_or_send(
            query,
            f"{header('📝', 'Isi Postingan')}\n"
            "Kirim isi postingan:\n• <b>Teks</b>, atau\n• <b>Foto/video</b> dengan caption.\n\n"
            "Format dasar (tebal, miring, link, kode) dari pesanmu ikut dipakai.\n"
            "Mau tombol di tengah teks? Tulis <code>{tombol}</code> di baris sendiri, lalu atur di 🔘 Tombol.\n"
            "Batas isi 32.000 karakter.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="rp_cancel")]]),
        )
        return

    if data == "rp_cancel":
        rich_draft.pop(uid, None); rich_wait.pop(uid, None)
        await edit_or_send(query, f"{header('📰', 'Rich Post')}\nDibatalkan.", _BACK_RICH)
        return

    if data == "rp_mine":
        rich_wait.pop(uid, None)
        n = len(get_rich_targets(uid))
        await edit_or_send(query, f"{header('📍', 'Tujuan Saya')}\n"
                                  + (f"{n} tujuan tersimpan. Tekan 🗑️ untuk menghapus." if n else "Belum ada tujuan. Tambahkan channel atau grup."),
                           _targets_kb(uid, manage=True))
        return

    if data == "rp_add":
        rich_wait[uid] = "target"
        back = "rp_targets" if uid in rich_draft else "rp_mine"
        await edit_or_send(
            query,
            f"{header('➕', 'Tambah Tujuan')}\n"
            f"Pastikan @{esc(context.bot.username)} sudah jadi <b>admin</b> di sana, lalu kirim salah satu:\n"
            "• <code>@username</code> atau link <code>t.me/username</code>\n"
            "• ID chat, contoh <code>-1001234567890</code>\n"
            "• <b>Forward</b> satu pesan dari channel itu (untuk channel privat)",
            InlineKeyboardMarkup([[Btn("🔙 Kembali", callback_data=back)]]),
        )
        return

    if data.startswith("rp_del:"):
        delete_rich_target(uid, int(data.split(":", 1)[1]))
        await edit_or_send(query, f"{header('📍', 'Tujuan Saya')}\nTujuan dihapus.", _targets_kb(uid, manage=True))
        return

    # Semua aksi di bawah memerlukan draf aktif
    d = rich_draft.get(uid)
    if d is None or (d["kind"] is None and not d["body"] and data != "rp_content"):
        await edit_or_send(query, f"{header('📰', 'Rich Post')}\nDraf tidak ditemukan atau sudah kedaluwarsa. Mulai lagi dari <b>Buat Postingan</b>.", _BACK_RICH)
        return

    # ── Panel dan kategori
    if data == "rp_panel":
        rich_wait.pop(uid, None); d["_pend"] = None
        await _panel(query, d)
    elif data == "rp_look":
        rich_wait.pop(uid, None)
        await _look_screen(query, d)
    elif data == "rp_send":
        await _send_screen(query, d)
    elif data == "rp_style":
        d["style"] = STYLES[(STYLES.index(d["style"]) + 1) % len(STYLES)]
        await _look_screen(query, d)
    elif data in ("rp_spoiler", "rp_divider"):
        d[data[3:]] = not d[data[3:]]
        await _look_screen(query, d)
    elif data in ("rp_silent", "rp_protect"):
        d[data[3:]] = not d[data[3:]]
        await _send_screen(query, d)
    elif data == "rp_tsize":
        d["title_size"] = d["title_size"] % 6 + 1
        await _look_screen(query, d)
    elif data == "rp_content":
        rich_wait[uid] = "content"
        await edit_or_send(query, f"{header('✏️', 'Ganti Isi')}\nKirim teks, atau foto/video dengan caption.",
                           _BACK_PANEL if d["body"] or d["kind"] else _BACK_RICH)
    elif data == "rp_title":
        rich_wait[uid] = "title"
        await edit_or_send(query, f"{header('🔤', 'Judul')}\nKirim teks judul (maks 120 karakter). Ketik <code>hapus</code> untuk menghapus judul.\n\n"
                                  "Pada gaya <b>Teks lipat</b>, judul menjadi tulisan yang selalu terlihat.", _BACK_LOOK)
    elif data == "rp_footer":
        rich_wait[uid] = "footer"
        await edit_or_send(query, f"{header('📝', 'Footer')}\nKirim teks footer (maks 200 karakter), misalnya nama channel. Ketik <code>hapus</code> untuk menghapus.", _BACK_LOOK)

    # ── Tombol
    elif data == "rp_buttons":
        rich_wait.pop(uid, None)
        await _buttons_screen(query, d)
    elif data.startswith("rp_btadd:"):
        t = data.split(":", 1)[1]
        if t not in BTN_TYPES:
            return
        if len(d["buttons"]) >= MAX_BUTTONS:
            await _buttons_screen(query, d, f"⚠️ Maksimal {MAX_BUTTONS} tombol. Hapus salah satu dulu.")
            return
        d["_btype"], d["_breplace"] = t, False
        rich_wait[uid] = "btn"
        await edit_or_send(query, f"{header(BTN_TYPES[t][0], 'Tombol ' + BTN_TYPES[t][1])}\n{_btn_prompt(t)}", _BACK_BTN)
    elif data == "rp_btmanual":
        d["_btype"], d["_breplace"] = None, True
        rich_wait[uid] = "btn"
        await edit_or_send(query, f"{header('✍️', 'Tulis Sekaligus')}\n{_btn_prompt(None)}\n\nKetik <code>hapus</code> untuk menghapus semua.", _BACK_BTN)
    elif data == "rp_btnpos":
        d["btn_pos"] = "bottom" if d["btn_pos"] == "inline" else "inline"
        await _buttons_screen(query, d)
    elif data == "rp_align":
        d["align"] = ALIGNS[(ALIGNS.index(d["align"]) + 1) % len(ALIGNS)]
        await _buttons_screen(query, d)
    elif data == "rp_btclear":
        d["buttons"] = []
        d["blocks"] = [b for b in d["blocks"] if b["t"] != "btns"]
        await _buttons_screen(query, d, "🧹 Semua tombol dihapus.")
    elif data == "rp_btlay":
        await _layout_screen(query, d)
    elif data.startswith(("rp_xup:", "rp_xjoin:", "rp_xdel:", "rp_xcols:")):
        act, arg = data[3:].split(":", 1)
        i = int(arg)
        bs = d["buttons"]
        if act == "xcols":
            for k, b in enumerate(bs):
                b["join"] = i > 1 and k % i != 0
        elif 0 <= i < len(bs):
            if act == "xup" and i > 0:
                bs[i - 1], bs[i] = bs[i], bs[i - 1]
            elif act == "xjoin" and i > 0:
                bs[i]["join"] = not bs[i].get("join")
            elif act == "xdel":
                bs.pop(i)
                if not bs:
                    d["blocks"] = [b for b in d["blocks"] if b["t"] != "btns"]
        await _layout_screen(query, d)

    # ── Blok dan urutan
    elif data == "rp_blocks":
        rich_wait.pop(uid, None)
        await _blocks_screen(query, d)
    elif data == "rp_badd_menu":
        rich_wait.pop(uid, None)
        await _badd_menu(query, d)
    elif data.startswith("rp_bcat:"):
        key = data.split(":", 1)[1]
        if key in BLOCK_CATS:
            await _bcat_screen(query, key)
    elif data.startswith("rp_badd:"):
        t = data.split(":", 1)[1]
        if t not in BLOCK_INFO or t.startswith("@"):
            return
        if len(extra_blocks(d["blocks"])) >= MAX_BLOCKS:
            await _blocks_screen(query, d, f"⚠️ Maksimal {MAX_BLOCKS} blok.")
        elif t == "btns":
            if not d["buttons"]:
                await _blocks_screen(query, d, "⚠️ Tambahkan tombol dulu lewat 🔘 Tombol di opsi utama.")
            else:
                d["btn_pos"] = "inline"
                d["blocks"].append({"t": "btns"})
                await _blocks_screen(query, d, "✅ Tombol ditaruh di posisi ini (mode Dalam teks aktif).")
        elif t == "divider":
            d["blocks"].append({"t": "divider"})
            await _blocks_screen(query, d, "✅ Pemisah ditambahkan.")
        elif t in OPTIONS:
            opts = OPTIONS[t]
            label = {"list": "Pilih jenis daftar:", "code": "Pilih bahasa kode:", "heading": "Pilih ukuran heading:", "gallery": "Pilih gaya galeri:"}[t]
            rows = [[Btn(name, callback_data=f"rp_bopt:{t}:{val}") for name, val in opts[i:i + 2]] for i in range(0, len(opts), 2)]
            rows.append([Btn("🔙 Kembali", callback_data="rp_badd_menu")])
            await edit_or_send(query, f"{header(BLOCK_INFO[t][0], BLOCK_INFO[t][1])}\n{label}", InlineKeyboardMarkup(rows))
        else:
            _ask_block(uid, d, t, None)
            await edit_or_send(query, f"{header(BLOCK_INFO[t][0], BLOCK_INFO[t][1])}\n{_block_prompt(t, None)}", _BLK_CANCEL)
    elif data.startswith("rp_bopt:"):
        _, t, opt = data.split(":", 2)
        _ask_block(uid, d, t, opt)
        await edit_or_send(query, f"{header(BLOCK_INFO[t][0], BLOCK_INFO[t][1])}\n{_block_prompt(t, opt)}",
                           _gallery_kb(d["_pend"]) if t == "gallery" else _BLK_CANCEL)
    elif data == "rp_bgsp":
        pend = d.get("_pend")
        if pend and pend["t"] == "gallery":
            pend["spoiler"] = not pend.get("spoiler")
            await edit_or_send(query, f"{header('🖼️', 'Galeri')}\n{_block_prompt('gallery', pend['opt'])}\n\n"
                                      f"Foto diterima: {len(pend['files'])}\n🙈 Spoiler menutupi semua foto sampai diketuk.",
                               _gallery_kb(pend))
    elif data == "rp_bdone":
        pend = d.get("_pend")
        if not pend or pend["t"] != "gallery" or len(pend["files"]) < 2:
            n = len(pend["files"]) if pend else 0
            await edit_or_send(query, f"⚠️ Baru {n} foto. Kirim minimal <b>2 foto</b> dulu, lalu tekan Selesai.",
                               _gallery_kb(pend or {}))
            return
        d["blocks"].append({"t": "gallery", "kind": pend["opt"], "files": pend["files"][:MAX_GALLERY],
                            "spoiler": bool(pend.get("spoiler"))})
        rich_wait.pop(uid, None)
        await _blocks_screen(query, d, "✅ Galeri ditambahkan.")
    elif data.startswith(("rp_bup:", "rp_bdn:", "rp_bdel:", "rp_bspoil:")):
        act, arg = data[3:].split(":", 1)
        i = int(arg)
        bl = d["blocks"]
        if 0 <= i < len(bl):
            if act == "bup" and i > 0:
                bl[i - 1], bl[i] = bl[i], bl[i - 1]
            elif act == "bdn" and i < len(bl) - 1:
                bl[i + 1], bl[i] = bl[i], bl[i + 1]
            elif act == "bdel" and not bl[i]["t"].startswith("@"):
                bl.pop(i)
            elif act == "bspoil" and bl[i]["t"] == "gallery":
                bl[i]["spoiler"] = not bl[i].get("spoiler")
        await _blocks_screen(query, d)

    # ── Pratinjau dan posting
    elif data == "rp_preview":
        await _preview(query, context, uid, d)
    elif data == "rp_targets":
        rich_wait.pop(uid, None)
        n = len(get_rich_targets(uid))
        await edit_or_send(query, f"{header('📤', 'Pilih Tujuan')}\n"
                                  + ("Pilih channel atau grup tujuan posting:" if n else "Belum ada tujuan. Tambahkan dulu."),
                           _targets_kb(uid))
    elif data.startswith("rp_t:"):
        await _confirm(query, context, uid, d, int(data.split(":", 1)[1]))
    elif data.startswith("rp_gobtn:"):
        d["btn_pos"] = "bottom"        # coba lagi dengan tombol biasa (bukan tombol dalam teks)
        await _post(query, context, uid, d, int(data.split(":", 1)[1]), plain=False)
    elif data.startswith("rp_go:") or data.startswith("rp_goplain:"):
        await _post(query, context, uid, d, int(data.split(":", 1)[1]), plain=data.startswith("rp_goplain:"))


async def _preview(query, context, uid: int, d: dict):
    try:
        await _send_rich(uid, uid, d, preview=True)
        note = "👆 Pratinjau Rich Message. Ini tampilan yang akan diposting. Tombol popup/vote aktif setelah diposting."
    except RichError as e:
        note = (f"⚠️ Pratinjau gagal: <code>{esc(e.description)}</code>\n"
                "Kamu masih bisa memposting sebagai pesan biasa (format terbatas)."
                + (" Atau ganti <b>Posisi tombol</b> ke Di bawah." if d["buttons"] and d["btn_pos"] == "inline" else ""))
    try:
        await query.message.delete()
    except TelegramError:
        pass
    await context.bot.send_message(uid, note, parse_mode=ParseMode.HTML)
    await context.bot.send_message(uid, _panel_text(d), reply_markup=_panel_kb(d), parse_mode=ParseMode.HTML)


async def _confirm(query, context, uid: int, d: dict, chat_id: int):
    chat, err = await _check_target(context.bot, chat_id, uid)
    if err:
        await edit_or_send(query, err, _BACK_PANEL)
        return
    await edit_or_send(
        query,
        f"{header('📤', 'Posting sekarang?')}\n"
        f"Tujuan: <b>{esc(chat.title)}</b>\nIsi: {esc(_content_label(d))}\nGaya: {STYLE_LABEL[d['style']]}"
        f"{'  •  Senyap' if d['silent'] else ''}{'  •  Dilindungi' if d['protect'] else ''}"
        + (f"\nTombol: {_btn_label(d)}" if d["buttons"] else ""),
        InlineKeyboardMarkup([[Btn("✅ Posting", callback_data=f"rp_go:{chat_id}")],
                              [Btn("🔙 Pilih tujuan lain", callback_data="rp_targets")]]),
    )


async def _post(query, context, uid: int, d: dict, chat_id: int, *, plain: bool):
    chat, err = await _check_target(context.bot, chat_id, uid)  # cek ulang tepat sebelum posting
    if err:
        await edit_or_send(query, err, _BACK_PANEL)
        return
    try:
        if plain:
            sent = await _send_plain(context.bot, uid, chat.id, d)
            mid = sent.message_id if sent else None
        else:
            sent = await _send_rich(uid, chat.id, d)
            mid = sent.get("message_id")
    except RichError as e:
        await edit_or_send(
            query,
            f"{header('⚠️', 'Rich Messages ditolak')}\n<code>{esc(e.description)}</code>\n\n"
            "Postingan <b>belum</b> dikirim. Kamu bisa mengirimnya sebagai pesan biasa (gaya lipat/panel jadi kutipan; "
            "musik, berkas, dan galeri dikirim terpisah), atau ubah opsinya.",
            InlineKeyboardMarkup([
                *([[Btn("🔘 Coba dengan tombol di bawah", callback_data=f"rp_gobtn:{chat_id}")]]
                  if d["buttons"] and d["btn_pos"] == "inline" else []),
                [Btn("📨 Kirim sebagai pesan biasa", callback_data=f"rp_goplain:{chat_id}")],
                [Btn("🔙 Kembali ke opsi", callback_data="rp_panel")]]),
        )
        return
    except TelegramError as e:
        await edit_or_send(query, f"❌ Gagal memposting: <code>{esc(str(e))}</code>", _BACK_PANEL)
        return
    link = post_link(chat.id, chat.username, mid) if mid else None
    rich_draft.pop(uid, None)
    await edit_or_send(
        query,
        f"{header('✅', 'Terposting')}\nPostingan terkirim ke <b>{esc(chat.title)}</b>"
        f"{' sebagai pesan biasa' if plain else ''}."
        + (f"\n\n{esc(link)}" if link else ""),
        InlineKeyboardMarkup([[Btn("📝 Buat Lagi", callback_data="rp_new")],
                              [Btn("🔙 Fitur VIP", callback_data="menu_fitur")]]),
    )


# ── Tombol popup dan vote pada postingan (dipencet siapa saja, bukan hanya VIP) ──────

_VOTE_TOAST = {"added": "👍 Suaramu tercatat", "moved": "🔄 Suaramu dipindah", "removed": "↩️ Suara dibatalkan"}


async def rich_public_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    try:
        if data.startswith("rpp:"):
            pid = int(data[4:])
            if pid == 0:
                await query.answer("👁 Ini pratinjau. Tombol aktif setelah diposting.", show_alert=True)
                return
            await query.answer((rich_popup_text(pid) or "Info tidak ditemukan.")[:200], show_alert=True)
        elif data.startswith("rpv:"):
            _, pid, idx = data.split(":")
            pid, idx = int(pid), int(idx)
            if pid == 0:
                await query.answer("👁 Ini pratinjau. Vote aktif setelah diposting.", show_alert=True)
                return
            action, counts = rich_vote_toggle(pid, query.from_user.id, idx)
            await query.answer(_VOTE_TOAST[action])
            kb = rich_poll_kb(pid)
            msg = query.message
            if kb and msg:
                try:
                    await edit_markup(BOT_TOKEN, msg.chat.id, msg.message_id, clean_markup(json.loads(kb), counts))
                except (RichError, ValueError):
                    pass          # mis. isi tidak berubah / pesan terlalu lama: suara tetap tercatat
        else:
            await query.answer()
    except Exception as e:
        try:
            await query.answer("Terjadi kesalahan, coba lagi.")
        except Exception:
            pass
        print(f"[rich] callback publik gagal: {e}")


# ── Input pesan ───────────────────────────────────────────────────────────────

async def handle_rich_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, uid = update.effective_message, update.effective_user.id
    step = rich_wait.get(uid)
    if not step:
        return
    if not is_subscribed(uid):
        rich_wait.pop(uid, None)
        await msg.reply_text("❌ VIP kamu sudah tidak aktif.", reply_markup=_BUY_KB)
        return
    d = rich_draft.setdefault(uid, _new_draft())
    text = (msg.text or "").strip()

    if step == "content":
        if msg.photo:
            kind, fid, body = "photo", msg.photo[-1].file_id, msg.caption_html or ""
        elif msg.video:
            kind, fid, body = "video", msg.video.file_id, msg.caption_html or ""
        elif msg.text:
            kind, fid, body = None, None, msg.text_html or ""
        else:
            await msg.reply_text("⚠️ Kirim teks, atau foto/video dengan caption.")
            return
        if not body.strip() and not kind:
            await msg.reply_text("⚠️ Isi tidak boleh kosong.")
            return
        if len(body) > MAX_RICH_CHARS - 2000:
            await msg.reply_text(f"⚠️ Isi terlalu panjang ({len(body)} karakter). Maksimal sekitar {MAX_RICH_CHARS - 2000}.")
            return
        d.update(kind=kind, file_id=fid, body=body)
        _sync_main(d)
    elif step == "title":
        if len(text) > 120:
            await msg.reply_text("⚠️ Judul maksimal 120 karakter. Kirim ulang.")
            return
        d["title"] = "" if text.lower() == "hapus" else text
    elif step == "footer":
        if len(text) > 200:
            await msg.reply_text("⚠️ Footer maksimal 200 karakter. Kirim ulang.")
            return
        d["footer"] = "" if text.lower() == "hapus" else text
    elif step == "btn":
        await _handle_button_input(msg, uid, d, text)
        return
    elif step == "target":
        await _handle_target_input(msg, context, uid)
        return
    elif step == "blk":
        await _handle_block_input(msg, uid, d)
        return

    rich_wait.pop(uid, None)
    await _panel(msg, d)


async def _handle_button_input(msg, uid: int, d: dict, text: str):
    if not text:
        await msg.reply_text("⚠️ Kirim dalam bentuk teks sesuai petunjuk.")
        return
    if text.lower() == "hapus":
        d["buttons"] = []
        d["blocks"] = [b for b in d["blocks"] if b["t"] != "btns"]
        notice = "🧹 Semua tombol dihapus."
    else:
        new, errors = parse_buttons(text, d.get("_btype"))
        if errors:
            await msg.reply_text("⚠️ " + "\n".join(errors) + "\n\nKirim ulang, atau tekan Kembali.", parse_mode=ParseMode.HTML)
            return
        merged = new if d.get("_breplace") else d["buttons"] + new
        if len(merged) > MAX_BUTTONS:
            await msg.reply_text(f"⚠️ Total tombol jadi {len(merged)}. Maksimal {MAX_BUTTONS}. Kirim lebih sedikit, atau hapus tombol lama.")
            return
        if sum(1 for b in merged if b["type"] == "vote") > MAX_VOTES:
            await msg.reply_text(f"⚠️ Maksimal {MAX_VOTES} tombol vote.")
            return
        d["buttons"] = merged
        notice = f"✅ {len(new)} tombol {'menggantikan yang lama' if d.get('_breplace') else 'ditambahkan'}."
    rich_wait.pop(uid, None)
    await _buttons_screen(msg, d, notice)


async def _handle_block_input(msg, uid: int, d: dict):
    pend = d.get("_pend")
    if not pend:
        rich_wait.pop(uid, None)
        return
    t, opt = pend["t"], pend["opt"]
    if t == "gallery":
        if not msg.photo:
            await msg.reply_text("⚠️ Kirim foto (bukan file). Tekan Selesai jika sudah cukup.")
            return
        if len(pend["files"]) >= MAX_GALLERY:
            await msg.reply_text(f"⚠️ Maksimal {MAX_GALLERY} foto. Tekan Selesai.")
            return
        pend["files"].append(msg.photo[-1].file_id)
        await msg.reply_text(f"🖼️ {len(pend['files'])} foto diterima. Kirim lagi atau tekan Selesai.",
                             reply_markup=_gallery_kb(pend))
        return
    if t in UPLOAD_BLOCKS:
        cap = (msg.caption or "").strip()[:200]
        if t == "audio":
            a, v = getattr(msg, "audio", None), getattr(msg, "voice", None)
            if not a and not v:
                await msg.reply_text("⚠️ Kirim sebagai <b>Audio</b> (musik) atau pesan suara, bukan sebagai file.",
                                     parse_mode=ParseMode.HTML)
                return
            if a:
                name = " - ".join(x for x in (a.performer, a.title) if x) or a.file_name or "Audio"
                block = {"t": "audio", "file_id": a.file_id, "name": name, "caption": cap}
            else:
                block = {"t": "audio", "file_id": v.file_id, "name": "Pesan suara", "caption": cap, "voice": True}
        else:
            doc = getattr(msg, "document", None)
            if not doc:
                await msg.reply_text("⚠️ Kirim sebagai <b>File/Dokumen</b> (📎 lalu File).", parse_mode=ParseMode.HTML)
                return
            block = {"t": "file", "file_id": doc.file_id, "name": doc.file_name or "Berkas", "caption": cap}
        d["blocks"].append(block)
        rich_wait.pop(uid, None)
        await _blocks_screen(msg, d, f"✅ {BLOCK_INFO[t][1]} ditambahkan: {esc(block['name'])}")
        return
    loc = (msg.location.latitude, msg.location.longitude) if getattr(msg, "location", None) else None
    if not msg.text and not loc:
        await msg.reply_text("⚠️ Kirim teks sesuai petunjuk.")
        return
    block, err = make_block(t, opt, msg.text or "", loc)
    if err:
        await msg.reply_text("⚠️ " + err + "\n\nKirim ulang, atau tekan Batal.", parse_mode=ParseMode.HTML)
        return
    d["blocks"].append(block)
    rich_wait.pop(uid, None)
    await _blocks_screen(msg, d, f"✅ {BLOCK_INFO[t][1]} ditambahkan.")


async def _handle_target_input(msg, context, uid: int):
    fo = getattr(msg, "forward_origin", None)
    ref = fo.chat.id if fo is not None and getattr(fo, "chat", None) else parse_chat_ref(msg.text or "")
    if ref is None:
        await msg.reply_text("⚠️ Tidak dikenali. Kirim <code>@username</code>, link t.me, ID chat, atau forward pesan dari channel itu.",
                             parse_mode=ParseMode.HTML)
        return
    chat, err = await _check_target(context.bot, ref, uid)
    if err:
        await msg.reply_text(err + "\n\nKirim tujuan lain, atau /cancel.", parse_mode=ParseMode.HTML)
        return
    if not add_rich_target(uid, chat.id, chat.title or str(chat.id), chat.type):
        await msg.reply_text("⚠️ Daftar tujuan penuh (maks 20). Hapus salah satu dulu.")
        rich_wait.pop(uid, None)
        return
    rich_wait.pop(uid, None)
    in_flow = uid in rich_draft and (rich_draft[uid]["body"] or rich_draft[uid]["kind"])
    await msg.reply_text(f"✅ <b>{esc(chat.title)}</b> ditambahkan sebagai tujuan.", parse_mode=ParseMode.HTML,
                         reply_markup=_targets_kb(uid) if in_flow else _targets_kb(uid, manage=True))
