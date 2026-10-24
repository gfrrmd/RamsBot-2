"""
Fitur VIP: Rich Post. Posting ke channel/grup memakai Rich Messages (Bot API 10.1+).

Alur (semua di chat dengan bot, tanpa session Telethon):
  1. Tambahkan bot sebagai admin di channel/grup tujuan, lalu daftarkan tujuannya di bot.
  2. Kirim isi postingan (teks, atau foto/video + caption).
  3. Pilih opsi format: gaya, judul, spoiler, pemisah, footer, tombol link.
  4. Pratinjau, pilih tujuan, Posting.

Keamanan: bot hanya memposting jika bot DAN pengguna sama-sama admin di tujuan tersebut.
Jika Rich Messages ditolak Telegram, posting tidak dikirim otomatis. Pengguna ditawari
kirim sebagai pesan biasa (HTML) lewat tombol terpisah.
"""
from telegram import CallbackQuery, InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from auth.states import clear_input_waits, rich_draft, rich_wait
from config import BOT_TOKEN
from database import add_rich_target, delete_rich_target, get_rich_targets, is_subscribed
from ui import edit_or_send, esc, header_e as header
from utils.rich import (
    ALIGN_LABEL, ALIGNS, BLOCK_INFO, BLOCK_ORDER, INSTANT_BLOCKS, MAX_BLOCKS, MAX_BUTTONS, MAX_CAPTION, MAX_COLS,
    MAX_GALLERY, MAX_RICH_CHARS, OPTIONS, STYLE_LABEL, STYLES, RichError,
    block_summary, build_plain_html, build_rich_html, make_block, media_list, parse_buttons, parse_chat_ref,
    post_link, send_rich,
)

_BUY_KB = InlineKeyboardMarkup([[Btn("💎 Beli / Perpanjang VIP", callback_data="pay_menu")],
                                [Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")]])
_BACK_RICH = InlineKeyboardMarkup([[Btn("🔙 Menu Rich Post", callback_data="fitur_rich")]])
_BACK_PANEL = InlineKeyboardMarkup([[Btn("🔙 Kembali ke opsi", callback_data="rp_panel")]])


# ── Draf ──────────────────────────────────────────────────────────────────────

def _new_draft() -> dict:
    return {"kind": None, "file_id": None, "body": "", "style": "normal", "title": "", "spoiler": False,
            "divider": False, "footer": "", "buttons": [], "btn_pos": "bottom", "cols": 1, "align": "left",
            "blocks": [], "title_size": 2, "_pend": None,
            "silent": False, "protect": False}


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
    return (
        f"{header('📰', 'Rich Post')}\n"
        f"<b>Isi:</b> {esc(_content_label(d))}\n"
        f"<b>Gaya:</b> {STYLE_LABEL[d['style']]}   <b>Judul:</b> {esc(d['title']) if d['title'] else '—'}\n"
        f"<b>Footer:</b> {esc(d['footer']) if d['footer'] else '—'}   <b>Tombol:</b> {_btn_label(d)}\n"
        f"<b>Blok tambahan:</b> {len(d['blocks'])}\n\n"
        "Atur opsi di bawah, cek <b>Pratinjau</b>, lalu pilih tujuan."
    )


def _button_layout_rows(d: dict) -> list:
    """Opsi posisi tombol. Kolom dan rata hanya relevan untuk tombol dalam teks."""
    if not d["buttons"]:
        return []
    rows = [[Btn(f"📍 Posisi: {'Dalam teks' if d['btn_pos'] == 'inline' else 'Di bawah (biasa)'}", callback_data="rp_btnpos")]]
    if d["btn_pos"] == "inline":
        rows.append([Btn(f"▦ Kolom: {d['cols']}", callback_data="rp_cols"),
                     Btn(f"↔️ Rata: {ALIGN_LABEL[d['align']]}", callback_data="rp_align")])
    return rows


def _panel_kb(d: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [Btn(f"🎨 Gaya: {STYLE_LABEL[d['style']]}", callback_data="rp_style")],
        [Btn(f"🙈 Spoiler: {_onoff(d['spoiler'])}", callback_data="rp_spoiler"),
         Btn(f"➖ Pemisah: {_onoff(d['divider'])}", callback_data="rp_divider")],
        [Btn("🔤 Judul", callback_data="rp_title"), Btn("📝 Footer", callback_data="rp_footer")],
        *([[Btn(f"🔠 Ukuran judul: H{d['title_size']}", callback_data="rp_tsize")]] if d["title"] and d["style"] != "details" else []),
        [Btn(f"🧱 Blok: daftar, tabel, kode, peta... ({len(d['blocks'])})", callback_data="rp_blocks")],
        [Btn(f"🔗 Tombol link ({len(d['buttons'])})", callback_data="rp_buttons")],
        *_button_layout_rows(d),
        [Btn(f"🔕 Senyap: {_onoff(d['silent'])}", callback_data="rp_silent"),
         Btn(f"🛡️ Lindungi: {_onoff(d['protect'])}", callback_data="rp_protect")],
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


# ── Pembuatan konten ──────────────────────────────────────────────────────────

def _rich_html(d: dict) -> str:
    return build_rich_html(d["body"], style=d["style"], title=d["title"], spoiler=d["spoiler"],
                           divider=d["divider"], footer=d["footer"], media_kind=d["kind"],
                           buttons=d["buttons"], buttons_inline=d["btn_pos"] == "inline",
                           cols=d["cols"], align=d["align"], blocks=d["blocks"], title_size=d["title_size"])


async def _send_rich(chat_id, d: dict):
    inline = d["btn_pos"] == "inline"
    return await send_rich(BOT_TOKEN, chat_id, _rich_html(d), media=media_list(d["kind"], d["file_id"], d["blocks"]),
                           buttons=None if inline else d["buttons"], silent=d["silent"], protect=d["protect"])


async def _send_plain(bot, chat_id, d: dict):
    """Cadangan: pesan biasa (HTML), caption dipakai bila media dan muat."""
    text = build_plain_html(d["body"], style=d["style"], title=d["title"], spoiler=d["spoiler"], footer=d["footer"], blocks=d["blocks"])
    mk = InlineKeyboardMarkup([[Btn(b[0], url=b[1])] for b in d["buttons"]]) if d["buttons"] else None
    common = dict(reply_markup=mk, disable_notification=d["silent"], protect_content=d["protect"])
    if d["kind"] in ("photo", "video"):
        send = bot.send_photo if d["kind"] == "photo" else bot.send_video
        if len(text) <= MAX_CAPTION:
            return await send(chat_id, d["file_id"], caption=text or None, parse_mode=ParseMode.HTML, **common)
        await send(chat_id, d["file_id"], disable_notification=d["silent"], protect_content=d["protect"])
        return await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, **common)
    return await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True, **common)


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


# ── Blok tambahan ─────────────────────────────────────────────────────────────

_BLOCK_PROMPTS = {
    "table": "Kirim tabel: satu baris per baris, kolom dipisah <code>|</code>. Baris pertama menjadi header.\n\n"
             "<code>Paket | Harga\nMingguan | 20rb\nBulanan | 50rb</code>",
    "quote": "Kirim teks kutipan. Sumber (opsional) ditulis setelah <code>|</code>.\n\n<code>Belajar tanpa henti | Budi</code>",
    "pull": "Kirim teks kutipan tengah. Sumber (opsional) ditulis setelah <code>|</code>.\n\n<code>Kualitas nomor satu | Redaksi</code>",
    "fold": "Baris pertama = judul yang selalu terlihat. Baris berikutnya = isi yang bisa dibuka.\n\n<code>Syarat\nMinimal 18 tahun\nBawa KTP</code>",
    "math": "Kirim rumus dalam format LaTeX.\n\n<code>E = mc^2</code>",
    "map": "Kirim <b>lokasi Telegram</b> (📎 lalu Lokasi), atau ketik koordinat.\n\n<code>-6.2088, 106.8456</code>",
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


async def _reply(target, text: str, kb=None):
    """Edit pesan jika dari tombol, kirim baru jika dari pesan."""
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, kb)
    else:
        await target.chat.send_message(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def _blocks_screen(target, d: dict, notice: str = ""):
    d["_pend"] = None
    lines = [f"{n}. {esc(block_summary(b))}" for n, b in enumerate(d["blocks"], 1)]
    text = (f"{header('🧱', 'Blok Tambahan')}\n{notice + chr(10) + chr(10) if notice else ''}"
            "Blok tampil <b>setelah isi utama</b>, berurutan dari atas.\n"
            + ("\n".join(lines) + "\n\n" if lines else "Belum ada blok.\n\n")
            + "Pilih jenis blok untuk ditambahkan:")
    rows = []
    for i, b in enumerate(d["blocks"]):
        rows.append([Btn(f"{i + 1}. {BLOCK_INFO[b['t']][0]} {BLOCK_INFO[b['t']][1]}"[:30], callback_data="rp_noop"),
                     *([Btn("⬆️", callback_data=f"rp_bup:{i}")] if i else []),
                     Btn("🗑️", callback_data=f"rp_bdel:{i}")])
    grid = [Btn(f"{BLOCK_INFO[t][0]} {BLOCK_INFO[t][1]}", callback_data=f"rp_badd:{t}") for t in BLOCK_ORDER]
    rows += [grid[i:i + 2] for i in range(0, len(grid), 2)]
    rows.append([Btn("🔙 Kembali ke opsi", callback_data="rp_panel")])
    await _reply(target, text, InlineKeyboardMarkup(rows))


def _ask_block(uid: int, d: dict, t: str, opt: str | None):
    d["_pend"] = {"t": t, "opt": opt, "files": []}
    rich_wait[uid] = "blk"


_BLK_CANCEL = InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="rp_blocks")]])


# ── Callback ──────────────────────────────────────────────────────────────────

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
            query,
            f"{header('📰', 'Rich Post')}\n"
            "Posting ke channel atau grup dengan format Rich Messages: judul, kutipan, teks lipat, spoiler, "
            "footer, tombol, plus blok <b>daftar, tabel, kode, kutipan, rumus, peta, galeri</b>. "
            "Semua lewat tombol. <b>Tidak perlu setup session.</b>\n\n"
            "📝 <b>Cara pakai:</b>\n"
            f"<b>1.</b> Jadikan @{esc(context.bot.username)} <b>admin</b> di channel/grup tujuan "
            "(di channel, aktifkan izin Post Messages).\n"
            "<b>2.</b> Tekan <b>Tujuan Saya</b>, lalu <b>Tambah Tujuan</b>.\n"
            "<b>3.</b> Tekan <b>Buat Postingan</b>, kirim teks, atau foto/video dengan caption.\n"
            "<b>4.</b> Pilih opsi format, tambah <b>🧱 Blok</b> bila perlu, cek pratinjau, pilih tujuan, lalu posting.\n\n"
            "ℹ️ Kamu juga harus admin di tujuan tersebut. Rich Messages tampil sempurna di Telegram versi terbaru.",
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
            "Mau tombol di tengah teks? Tulis <code>{tombol}</code> di baris sendiri, lalu atur di opsi 🔗 Tombol link.\n"
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

    if data == "rp_panel":
        rich_wait.pop(uid, None); d["_pend"] = None
        await _panel(query, d)
    elif data == "rp_style":
        d["style"] = STYLES[(STYLES.index(d["style"]) + 1) % len(STYLES)]
        await _panel(query, d)
    elif data == "rp_btnpos":
        d["btn_pos"] = "bottom" if d["btn_pos"] == "inline" else "inline"
        await _panel(query, d)
    elif data == "rp_cols":
        d["cols"] = d["cols"] % MAX_COLS + 1
        await _panel(query, d)
    elif data == "rp_align":
        d["align"] = ALIGNS[(ALIGNS.index(d["align"]) + 1) % len(ALIGNS)]
        await _panel(query, d)
    elif data in ("rp_spoiler", "rp_divider", "rp_silent", "rp_protect"):
        key = data[3:]
        d[key] = not d[key]
        await _panel(query, d)
    elif data == "rp_content":
        rich_wait[uid] = "content"
        await edit_or_send(query, f"{header('✏️', 'Ganti Isi')}\nKirim teks, atau foto/video dengan caption.",
                           _BACK_PANEL if d["body"] or d["kind"] else _BACK_RICH)
    elif data == "rp_title":
        rich_wait[uid] = "title"
        await edit_or_send(query, f"{header('🔤', 'Judul')}\nKirim teks judul (maks 120 karakter). Ketik <code>hapus</code> untuk menghapus judul.\n\n"
                                  "Pada gaya <b>Teks lipat</b>, judul menjadi tulisan yang selalu terlihat.", _BACK_PANEL)
    elif data == "rp_footer":
        rich_wait[uid] = "footer"
        await edit_or_send(query, f"{header('📝', 'Footer')}\nKirim teks footer (maks 200 karakter), misalnya nama channel. Ketik <code>hapus</code> untuk menghapus.", _BACK_PANEL)
    elif data == "rp_buttons":
        rich_wait[uid] = "buttons"
        await edit_or_send(
            query,
            f"{header('🔗', 'Tombol Link')}\nSatu tombol per baris, format:\n<code>Teks | https://link</code>\n"
            "Warna (opsional): <code>Teks | https://link | hijau</code>. Pilihan: biru, hijau, merah, polos.\n\n"
            f"Contoh:\n<code>Gabung Channel | https://t.me/namachannel | biru\nBuka Website | https://contoh.com</code>\n\n"
            f"Maksimal {MAX_BUTTONS} tombol. Ketik <code>hapus</code> untuk menghapus semua.\n\n"
            "📍 <b>Posisi:</b> setelah menyimpan tombol, pilih <b>Posisi: Dalam teks</b> di panel. "
            "Tombol otomatis di akhir isi. Untuk menaruhnya di tengah teks, tulis di isi postingan, di baris sendiri:\n"
            "<code>{tombol}</code> = semua tombol\n<code>{tombol:2}</code> = hanya tombol nomor 2\n"
            "Tombol yang tidak ditunjuk penanda ditaruh di akhir.", _BACK_PANEL)
    elif data == "rp_tsize":
        d["title_size"] = d["title_size"] % 6 + 1
        await _panel(query, d)
    elif data == "rp_blocks":
        rich_wait.pop(uid, None)
        await _blocks_screen(query, d)
    elif data.startswith("rp_badd:"):
        t = data.split(":", 1)[1]
        if t not in BLOCK_INFO:
            return
        if len(d["blocks"]) >= MAX_BLOCKS:
            await _blocks_screen(query, d, f"⚠️ Maksimal {MAX_BLOCKS} blok.")
        elif t == "btns":
            if not d["buttons"]:
                await _blocks_screen(query, d, "⚠️ Tambahkan tombol dulu lewat 🔗 Tombol link di opsi utama.")
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
            rows.append([Btn("🔙 Kembali", callback_data="rp_blocks")])
            await edit_or_send(query, f"{header(BLOCK_INFO[t][0], BLOCK_INFO[t][1])}\n{label}", InlineKeyboardMarkup(rows))
        else:
            _ask_block(uid, d, t, None)
            await edit_or_send(query, f"{header(BLOCK_INFO[t][0], BLOCK_INFO[t][1])}\n{_block_prompt(t, None)}", _BLK_CANCEL)
    elif data.startswith("rp_bopt:"):
        _, t, opt = data.split(":", 2)
        _ask_block(uid, d, t, opt)
        await edit_or_send(query, f"{header(BLOCK_INFO[t][0], BLOCK_INFO[t][1])}\n{_block_prompt(t, opt)}",
                           InlineKeyboardMarkup([[Btn("✅ Selesai", callback_data="rp_bdone")], [Btn("❌ Batal", callback_data="rp_blocks")]])
                           if t == "gallery" else _BLK_CANCEL)
    elif data == "rp_bdone":
        pend = d.get("_pend")
        if not pend or pend["t"] != "gallery" or len(pend["files"]) < 2:
            n = len(pend["files"]) if pend else 0
            await edit_or_send(query, f"⚠️ Baru {n} foto. Kirim minimal <b>2 foto</b> dulu, lalu tekan Selesai.",
                               InlineKeyboardMarkup([[Btn("✅ Selesai", callback_data="rp_bdone")],
                                                     [Btn("❌ Batal", callback_data="rp_blocks")]]))
            return
        d["blocks"].append({"t": "gallery", "kind": pend["opt"], "files": pend["files"][:MAX_GALLERY]})
        rich_wait.pop(uid, None)
        await _blocks_screen(query, d, "✅ Galeri ditambahkan.")
    elif data.startswith("rp_bup:") or data.startswith("rp_bdel:"):
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(d["blocks"]):
            if data.startswith("rp_bup:") and i > 0:
                d["blocks"][i - 1], d["blocks"][i] = d["blocks"][i], d["blocks"][i - 1]
            elif data.startswith("rp_bdel:"):
                d["blocks"].pop(i)
        await _blocks_screen(query, d)
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
        await _send_rich(uid, d)
        note = "👆 Pratinjau Rich Message. Ini tampilan yang akan diposting."
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
            sent = await _send_plain(context.bot, chat.id, d)
            mid = sent.message_id
        else:
            sent = await _send_rich(chat.id, d)
            mid = sent.get("message_id")
    except RichError as e:
        await edit_or_send(
            query,
            f"{header('⚠️', 'Rich Messages ditolak')}\n<code>{esc(e.description)}</code>\n\n"
            "Postingan <b>belum</b> dikirim. Kamu bisa mengirimnya sebagai pesan biasa (gaya lipat/panel jadi kutipan), atau ubah opsinya.",
            InlineKeyboardMarkup([
                *([[Btn("🔘 Coba dengan tombol biasa", callback_data=f"rp_gobtn:{chat_id}")]]
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
    elif step == "buttons":
        if text.lower() == "hapus":
            d["buttons"] = []
        else:
            buttons, errors = parse_buttons(text)
            if errors:
                await msg.reply_text("⚠️ " + "\n".join(errors) + "\n\nKirim ulang, atau /cancel.", parse_mode=ParseMode.HTML)
                return
            d["buttons"] = buttons
    elif step == "target":
        await _handle_target_input(msg, context, uid)
        return
    elif step == "blk":
        await _handle_block_input(msg, uid, d)
        return

    rich_wait.pop(uid, None)
    await _panel(msg, d)


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
                             reply_markup=InlineKeyboardMarkup([[Btn("✅ Selesai", callback_data="rp_bdone")],
                                                                [Btn("❌ Batal", callback_data="rp_blocks")]]))
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
