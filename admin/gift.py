from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database import activate_subscription, get_user_by_username, upsert_user
from keyboards import admin_keyboard
from services.session_runner import ensure_client_running


async def _do_gift(target_str: str, days: int, context) -> tuple[bool, str]:
    clean = target_str.lstrip("@")
    if clean.isdigit():
        target_id = int(clean)
    else:
        target_id = get_user_by_username(clean)
        if target_id is None:
            return False, f"❌ Username @{clean} tidak ditemukan di database.\n\n💡 Gunakan user ID (angka) agar bisa gift tanpa user perlu klik /start dulu."
    upsert_user(target_id, None, None)
    expired = activate_subscription(target_id, days=days)
    try:
        await ensure_client_running(target_id, context.bot)   # aktifkan lagi session tersimpan
    except Exception:
        pass
    notif_sent = False
    try:
        await context.bot.send_message(chat_id=target_id, text=f"🎁 Selamat! VIP kamu telah diaktifkan!\n\n📅 Aktif hingga: {expired.strftime('%d %b %Y')}\n⏳ Durasi: {days} hari\n\nKetik /start untuk melihat status VIP kamu.")
        notif_sent = True
    except Exception:
        pass
    notif_info = "" if notif_sent else "\n⚠️ Notifikasi ke user gagal dikirim (user belum pernah start bot)."
    return True, f"🎁 VIP berhasil diberikan ke {target_id} selama {days} hari\nAktif hingga: {expired.strftime('%d %b %Y')}{notif_info}"


async def cmd_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        await update.message.reply_text("❌ Kamu tidak memiliki izin."); return
    if not context.args:
        await update.message.reply_text("⚠️ Format: /gift <user_id atau @username> [hari]\nContoh: /gift 123456789 30"); return
    target_str = context.args[0].strip()
    days = int(context.args[1]) if len(context.args) > 1 and context.args[1].isdigit() else 30
    ok, msg = await _do_gift(target_str, days, context)
    await update.message.reply_text(msg, reply_markup=admin_keyboard() if ok else None)
