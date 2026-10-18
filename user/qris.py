"""
Fitur QRIS Dinamis untuk user VIP.

  • Setup (di bot): Fitur VIP → 💳 QRIS Dinamis → kirim gambar QRIS statis.
  • Pakai (di chat mana pun): `.qris 25000` → bot mengubah QRIS statis jadi dinamis
    dengan nominal tersebut dan mengirim gambarnya di chat yang sama.
"""
import asyncio
import io

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telethon import events

from auth.states import clear_input_waits, waiting_qris_upload
from client_manager import active_clients, stop_client_for_user
from database import delete_user_qris, get_user_qris, is_subscribed, save_user_qris
from keyboards import qris_keyboard
from ui import edit_or_send, esc, fmt_dt, header, replace_with_photo
from utils.helpers import escape_md
from utils.qris import (
    MAX_AMOUNT,
    QRISError,
    convert_qris,
    decode_qr_image,
    extract_qris_from_text,
    format_rupiah,
    parse_amount,
    render_qr_png,
    summarize_qris,
    validate_qris,
)

MAX_IMAGE_BYTES = 10 * 1024 * 1024
_CANCEL_KB = InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="fitur_qris")]])
_BUY_KB = InlineKeyboardMarkup([[Btn("💎 Beli / Perpanjang VIP", callback_data="pay_menu")],
                                [Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")]])


# ═══════════════════════════════════════════════════════════════════════════════
#  Telethon: command .qris
# ═══════════════════════════════════════════════════════════════════════════════

def register_qris_handler(client, user_id: int):
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.qris(?:\s+(.+))?$"))
    async def qris_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me", "❌ Langganan VIP kamu sudah habis atau dicabut.\nHubungi admin untuk memperpanjang.")
            return

        arg = (event.pattern_match.group(1) or "").strip()
        chat_id = event.chat_id
        reply_to = event.reply_to_msg_id
        try:
            await event.delete()
        except Exception:
            pass

        amount = parse_amount(arg) if arg else None
        if amount is None:
            await client.send_message(
                "me",
                "💳 **QRIS Dinamis**\n\nFormat: `.qris (nominal)`\n\n"
                "Contoh:\n`.qris 25000`\n`.qris 25.000`\n`.qris 25k`\n`.qris 1,5jt`",
            )
            return
        if amount > MAX_AMOUNT:
            await client.send_message("me", f"❌ Nominal terlalu besar (maksimal {format_rupiah(MAX_AMOUNT)}).")
            return

        saved = get_user_qris(user_id)
        if not saved:
            await client.send_message(
                "me",
                "❌ **Belum ada QRIS tersimpan.**\n\nBuka bot → 🎯 Fitur VIP → 💳 QRIS Dinamis, "
                "lalu kirim gambar QRIS statis kamu.",
            )
            return

        try:
            payload = convert_qris(saved["qris_string"], amount)
            png = await asyncio.to_thread(render_qr_png, payload, "QRIS", saved["merchant_name"], amount)
        except QRISError as e:
            await client.send_message("me", f"❌ {e}")
            return
        except Exception as e:
            await client.send_message("me", f"❌ Gagal membuat QRIS: {e}\n\nCoba upload ulang QRIS statis kamu di bot.")
            return

        bio = io.BytesIO(png)
        bio.name = "qris.png"
        merchant = escape_md(saved["merchant_name"]) if saved["merchant_name"] else "—"
        caption = (
            "💳 **QRIS Pembayaran**\n"
            f"🏪 {merchant}\n"
            f"💰 **Nominal:** {format_rupiah(amount)}\n\n"
            "Scan QR di atas dengan e-wallet / m-banking."
        )
        try:
            await client.send_file(chat_id, bio, caption=caption, reply_to=reply_to)
        except Exception as e:
            await client.send_message("me", f"❌ Gagal mengirim QRIS ke chat: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Bot: menu setup QRIS
# ═══════════════════════════════════════════════════════════════════════════════

def _menu_text(uid: int) -> str:
    saved = get_user_qris(uid)
    client = active_clients.get(uid)
    session_ok = bool(client and client.is_connected())
    if saved:
        data = (
            "Status: Tersimpan ✅\n"
            f"Merchant: {esc(saved['merchant_name'])}\n"
            f"Kota: {esc(saved['merchant_city'])}\n"
            f"Diperbarui: {esc(fmt_dt(saved['updated_at']))}"
        )
    else:
        data = "Status: Belum ada QRIS ❌"
    warn = "" if session_ok else "\n\n⚠️ Session belum aktif. Selesaikan <b>Setup Bot</b> dulu agar command <code>.qris</code> bisa dipakai."
    return (
        f"{header('💳', 'QRIS Dinamis')}\n"
        "Ubah <b>QRIS statis</b> tokomu menjadi <b>QRIS dinamis</b> dengan nominal otomatis, langsung dari chat mana pun.\n\n"
        f"{data}\n\n"
        "📝 <b>Cara pakai:</b>\n"
        "<code>.qris (nominal)</code>\n\n"
        "💡 <b>Contoh:</b>\n"
        "<code>.qris 25000</code>\n<code>.qris 25k</code>\n<code>.qris 1,5jt</code>"
        f"{warn}"
    )


async def show_qris_menu(query, uid: int):
    await edit_or_send(query, _menu_text(uid), qris_keyboard(bool(get_user_qris(uid))))


async def qris_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()
    clear_input_waits(uid)

    if not is_subscribed(uid):
        await edit_or_send(
            query,
            f"{header('💳', 'QRIS Dinamis')}\nFitur ini khusus <b>user VIP</b>. Beli atau perpanjang VIP untuk memakainya.",
            _BUY_KB,
        )
        return

    if data == "fitur_qris":
        await show_qris_menu(query, uid)
        return

    if data == "qris_upload":
        waiting_qris_upload.add(uid)
        await edit_or_send(
            query,
            f"{header('📤', 'Upload QRIS Statis')}\n"
            "Kirim <b>gambar QRIS statis</b> tokomu (screenshot atau foto, boleh sebagai file).\n\n"
            "✅ Pastikan QR terlihat penuh, tidak blur & tidak terpotong.\n"
            "✅ Alternatif: tempel kode QRIS-nya sebagai teks (diawali <code>000201</code>).\n\n"
            "Ketik /cancel atau tekan Batal untuk membatalkan.",
            _CANCEL_KB,
        )
        return

    if data == "qris_view":
        saved = get_user_qris(uid)
        if not saved:
            await show_qris_menu(query, uid)
            return
        png = await asyncio.to_thread(render_qr_png, saved["qris_string"], "QRIS Statis", saved["merchant_name"])
        await replace_with_photo(
            query, png,
            f"🏪 <b>{esc(saved['merchant_name'])}</b>\n{esc(saved['merchant_city'])}\n\n"
            "Ini QRIS statis yang tersimpan. Gunakan <code>.qris (nominal)</code> untuk membuat versi dinamisnya.",
            InlineKeyboardMarkup([[Btn("🔙 Menu QRIS", callback_data="fitur_qris")]]),
        )
        return

    if data == "qris_delete":
        await edit_or_send(
            query,
            f"{header('🗑️', 'Hapus QRIS?')}\nQRIS statis tersimpan akan dihapus. Command <code>.qris</code> tidak bisa dipakai sampai kamu upload lagi.",
            InlineKeyboardMarkup([[Btn("✅ Ya, hapus", callback_data="qris_delete_yes"), Btn("❌ Batal", callback_data="fitur_qris")]]),
        )
        return

    if data == "qris_delete_yes":
        delete_user_qris(uid)
        await show_qris_menu(query, uid)
        return


async def extract_qris_from_message(msg) -> tuple[str | None, str | None]:
    """
    Ambil string QRIS dari pesan (foto / file gambar / teks mentah).
    Return (qris, None) bila berhasil, atau (None, pesan_error_html).
    Dipakai bersama oleh setup QRIS user dan setup QRIS pembayaran admin.
    """
    if msg.photo or (msg.document and (msg.document.mime_type or "").startswith("image/")):
        obj = msg.photo[-1] if msg.photo else msg.document
        if (obj.file_size or 0) > MAX_IMAGE_BYTES:
            return None, "❌ Ukuran gambar terlalu besar (maks 10 MB). Kirim ulang gambar yang lebih kecil."
        status = await msg.reply_text("🔍 Membaca QR dari gambar...")
        tg_file = await obj.get_file()
        data = bytes(await tg_file.download_as_bytearray())
        qris = await asyncio.to_thread(decode_qr_image, data)
        try:
            await status.delete()
        except Exception:
            pass
        if not qris:
            return None, (
                "❌ <b>QR tidak terbaca.</b>\n\nCoba kirim gambar yang lebih jelas (QR penuh, tidak blur/terpotong), "
                "atau tempel kode QRIS sebagai teks (diawali <code>000201</code>).\n\nAtau /cancel untuk batal."
            )
    elif msg.text:
        qris = extract_qris_from_text(msg.text)
        if not qris:
            return None, ("⚠️ Kirim <b>gambar</b> QRIS statis, atau tempel kode QRIS "
                          "(diawali <code>000201</code>). /cancel untuk batal.")
    else:
        return None, "⚠️ Kirim gambar QRIS dalam bentuk foto atau file gambar."

    errors = validate_qris(qris)
    if errors:
        listed = "\n".join(f"• {esc(e)}" for e in errors[:3])
        return None, f"❌ <b>QR terbaca, tapi bukan QRIS yang valid:</b>\n{listed}\n\nCoba kirim QRIS yang benar, atau /cancel."
    return qris, None


async def handle_qris_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dipanggil saat user dalam mode upload QRIS mengirim gambar / teks."""
    msg = update.effective_message
    uid = update.effective_user.id

    if not is_subscribed(uid):
        clear_input_waits(uid)
        await msg.reply_text("❌ Langganan VIP kamu tidak aktif.", reply_markup=_BUY_KB)
        return

    qris, err = await extract_qris_from_message(msg)
    if err:
        await msg.reply_text(err, parse_mode=ParseMode.HTML)
        return

    info = summarize_qris(qris)
    save_user_qris(uid, qris, info["merchant_name"], info["merchant_city"])
    waiting_qris_upload.discard(uid)

    note = ""
    if info["method"] == "dynamic":
        note = "\n\nℹ️ QRIS ini sudah berbentuk dinamis. Tidak masalah — nominalnya akan diganti sesuai <code>.qris (nominal)</code>."
    caption = (
        f"✅ <b>QRIS tersimpan!</b>\n"
        f"🏪 {esc(info['merchant_name'])} - {esc(info['merchant_city'])}\n\n"
        "Sekarang ketik di chat mana pun:\n<code>.qris 10000</code>\n\n"
        f"Gambar di atas adalah contoh hasil untuk Rp 10.000.{note}"
    )
    try:
        sample = await asyncio.to_thread(
            render_qr_png, convert_qris(qris, 10000), "QRIS", info["merchant_name"], 10000)
        await msg.reply_photo(sample, caption=caption, parse_mode=ParseMode.HTML,
                              reply_markup=InlineKeyboardMarkup([[Btn("💳 Menu QRIS", callback_data="fitur_qris")],
                                                                 [Btn("🏠 Menu Utama", callback_data="menu_back")]]))
    except Exception:
        await msg.reply_text(caption, parse_mode=ParseMode.HTML)
