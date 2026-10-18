import asyncio
import time
from datetime import timezone, timedelta

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telethon.errors import PhoneCodeExpiredError, PhoneCodeInvalidError, SessionPasswordNeededError

from auth.states import CODE_STEP, PASSWORD_STEP, PHONE_STEP, temp_store
from client_manager import active_clients, build_client, dl_locks, _start_time
from config import API_ID, API_HASH
from database import activate_trial, is_subscribed, save_user_session
from keyboards import main_keyboard, not_subscribed_keyboard, trial_activated_keyboard
from user.download import register_download_handler
from user.copy import register_copy_handler
from user.story import register_story_handler
from user.auto_dl import register_auto_dl_handler
from user.ping import register_ping_handler
from user.qris import register_qris_handler
from user.broadcast import register_broadcast_handler
from user.join_request import register_join_request_handler
from user.auto_block_leaver import register_auto_block_leaver_handler
from user.outgoing_timer_log import register_outgoing_timer_log_handler
from admin.cekvip import register as register_cekvip_handler

WIB = timezone(timedelta(hours=7))

# PTB bot instance — diset dari main.py setelah app.build()
_ptb_bot = None


def set_ptb_bot(bot):
    """Dipanggil dari main.py setelah PTB Application siap."""
    global _ptb_bot
    _ptb_bot = bot


def register_telethon_handlers(client, user_id: int, bot_client=None):
    # FIX: gunakan bot_client yang di-pass secara eksplisit jika ada,
    # fallback ke _ptb_bot global (untuk path setup baru)
    resolved_bot = bot_client if bot_client is not None else _ptb_bot
    if resolved_bot is None:
        print(f"[setup] WARNING: bot_client None saat register handler user {user_id} — log tidak akan terkirim")
    register_ping_handler(client, user_id)
    register_download_handler(client, user_id, bot_client=resolved_bot)
    register_copy_handler(client, user_id)
    register_story_handler(client, user_id, bot_client=resolved_bot)
    register_auto_dl_handler(client, user_id, bot_client=resolved_bot)
    register_broadcast_handler(client, user_id)
    register_join_request_handler(client, user_id)
    register_auto_block_leaver_handler(client, user_id)
    register_outgoing_timer_log_handler(client, user_id, bot_client=resolved_bot)
    register_qris_handler(client, user_id)
    register_cekvip_handler(client)


async def _ask_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*🤖 Setup Bot Telegram*\n\n"
        "Proses ini menghubungkan akun Telegram ke bot.\n\n"
        "*Langkah 1/3 — Nomor HP 📲*\n\n"
        "Masukkan nomor HP yang terdaftar di akun Telegram kamu.\n"
        "Contoh: `+6281234567890`\n\n"
        "Kirim nomor HP kamu, atau /cancel untuk batal:"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")
    return PHONE_STEP


async def setup_agree_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    await update.callback_query.answer()
    temp_store.pop(uid, None)
    if not is_subscribed(uid):
        await update.callback_query.edit_message_text(
            "☹️ *Kamu belum berlangganan VIP.*\n"
            "Beli VIP langsung lewat bot (tombol di bawah) atau coba trial gratis jika tersedia.",
            parse_mode="Markdown",
            reply_markup=not_subscribed_keyboard(uid),
        )
        return ConversationHandler.END
    return await _ask_phone_number(update, context)


async def setup_try_trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    await update.callback_query.answer()
    success, expired, minutes = activate_trial(uid)
    if not success:
        await update.callback_query.edit_message_text(
            "⚠️ *Trial sudah pernah digunakan.*\n\n"
            "Silakan berlangganan VIP untuk melanjutkan setup.",
            parse_mode="Markdown",
            reply_markup=not_subscribed_keyboard(uid),
        )
        return ConversationHandler.END

    expired_wib = expired.astimezone(WIB)

    if minutes >= 1440:
        hari = minutes // 1440
        durasi_str = f"{hari} hari"
    elif minutes >= 60:
        jam = minutes // 60
        durasi_str = f"{jam} jam"
    else:
        durasi_str = f"{minutes} menit"

    exp_str = expired_wib.strftime("%H:%M WIB, %d %b %Y")
    await update.callback_query.edit_message_text(
        f"🎉 *Free Trial Aktif!*\n\n"
        f"⏳ Durasi: *{durasi_str}*\n"
        f"🕐 Berakhir: *{exp_str}*\n\n"
        f"Kamu sekarang bisa menikmati semua fitur bot. Klik tombol di bawah untuk melanjutkan setup session.",
        parse_mode="Markdown",
        reply_markup=trial_activated_keyboard(),
    )
    return ConversationHandler.END


async def setup_continue_after_trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.callback_query.from_user.id
    await update.callback_query.answer()
    temp_store.pop(uid, None)
    return await _ask_phone_number(update, context)


async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_subscribed(uid):
        await update.message.reply_text(
            "❌ Kamu belum berlangganan VIP.\nBeli VIP lewat tombol 💎 *Beli / Perpanjang VIP* di menu.",
            parse_mode="Markdown",
            reply_markup=main_keyboard(uid)
        )
        return ConversationHandler.END
    temp_store.pop(uid, None)
    return await _ask_phone_number(update, context)


async def setup_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    phone = update.message.text.strip()
    client = build_client(API_ID, API_HASH)
    try:
        await client.connect()
        result = await client.send_code_request(phone)
        temp_store[uid] = {"phone": phone, "phone_hash": result.phone_code_hash, "client": client}
        await update.message.reply_text(
            "📨 Kode OTP berhasil dikirim ke Telegram kamu!\n\n"
            "*Langkah 2/3 — Kode OTP 🔢*\n\n"
            "Ketik kode dengan spasi di antara setiap angka.\n\n"
            "✅ Contoh Benar: `1 2 3 4 5`\n"
            "❌ Contoh Salah: `12345`\n\n"
            "Kirim kode OTP kamu, atau /cancel untuk batal:",
            parse_mode="Markdown",
        )
        return CODE_STEP
    except Exception as e:
        await client.disconnect()
        temp_store.pop(uid, None)
        await update.message.reply_text(
            f"❌ Gagal mengirim OTP: {e}\n\nSilakan /setup ulang dari awal.",
            reply_markup=main_keyboard(uid)
        )
        return ConversationHandler.END


async def setup_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    code = update.message.text.strip().replace(" ", "")
    data = temp_store.get(uid, {})
    client = data.get("client")
    try:
        await client.sign_in(data["phone"], code, phone_code_hash=data["phone_hash"])
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔐 Akun kamu mengaktifkan verifikasi 2 langkah (2FA)\n\n"
            "*Langkah 3/3 — Password 2FA*\n\n"
            "Masukkan password 2FA Telegram kamu, atau /cancel untuk batal:",
            parse_mode="Markdown",
        )
        return PASSWORD_STEP
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await client.disconnect()
        temp_store.pop(uid, None)
        await update.message.reply_text("❌ Kode OTP salah atau sudah kadaluarsa. Silakan /setup ulang.")
        return ConversationHandler.END
    except Exception as e:
        await client.disconnect()
        temp_store.pop(uid, None)
        await update.message.reply_text(f"❌ Terjadi error: {e}\n\nSilakan /setup ulang.")
        return ConversationHandler.END
    return await _finish_setup(update, uid, data, client)


async def setup_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = temp_store.get(uid, {})
    client = data.get("client")
    try:
        await client.sign_in(password=update.message.text.strip())
    except Exception as e:
        await client.disconnect()
        temp_store.pop(uid, None)
        await update.message.reply_text(f"❌ Password 2FA salah: {e}\n\nSilakan /setup ulang.")
        return ConversationHandler.END
    return await _finish_setup(update, uid, data, client)


async def _finish_setup(update, uid, data, client):
    string_session = client.session.save()
    save_user_session(uid, API_ID, API_HASH, string_session)

    old = active_clients.get(uid)
    if old and old.is_connected():
        await old.disconnect()
    dl_locks.setdefault(uid, asyncio.Lock())
    await client.start()
    _start_time[uid] = time.monotonic()
    register_telethon_handlers(client, uid)
    active_clients[uid] = client
    asyncio.ensure_future(client.run_until_disconnected())

    temp_store.pop(uid, None)
    await update.message.reply_text(
        "✅ *Setup berhasil! Session kamu sudah aktif.*\n\n"
        "⚠️ *PENTING: Jangan logout dari sesi ini!*\n\n"
        "Bot bekerja menggunakan sesi login akun Telegram kamu yang sudah tersimpan. Jika kamu logout dari perangkat tempat sesi ini dibuat, maka semua fitur (.dl, .copy, .qris, dll) akan berhenti berfungsi dan kamu perlu /setup ulang.\n\n"
        "💡 Gunakan tombol 🎯 *Fitur VIP* di menu utama untuk panduan lengkap setiap fitur.",
        parse_mode="Markdown",
        reply_markup=main_keyboard(uid),
    )
    return ConversationHandler.END
