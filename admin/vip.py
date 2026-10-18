from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from client_manager import stop_client_for_user
from database import get_user_by_username, is_subscribed, revoke_subscription
from keyboards import admin_keyboard


def _find_subscribed_user(target_str: str):
    clean = target_str.lstrip("@")
    if clean.isdigit():
        return int(clean)
    return get_user_by_username(clean)


async def _do_revoke(target_str: str, context) -> tuple[bool, str]:
    target_id = _find_subscribed_user(target_str)
    if target_id is None:
        return False, f"❌ User {target_str} tidak ditemukan di database.\n\nGunakan user ID (angka) jika username tidak terdaftar."
    if not is_subscribed(target_id):
        return False, f"⚠️ User {target_id} tidak memiliki langganan VIP aktif.\n\nMungkin VIP sudah pernah dicabut sebelumnya."
    revoke_subscription(target_id)
    await stop_client_for_user(target_id)
    notif_sent = False
    try:
        await context.bot.send_message(chat_id=target_id, text="🚫 VIP kamu telah dicabut oleh admin.\n\nFitur .dl dan .copy tidak lagi bisa digunakan.\nHubungi admin jika ada pertanyaan.")
        notif_sent = True
    except Exception:
        pass
    return True, f"✅ VIP user {target_id} berhasil dicabut. Client langsung dihentikan.{'' if notif_sent else '\n⚠️ Notifikasi ke user gagal dikirim.'}"


async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        await update.message.reply_text("❌ Kamu tidak memiliki izin."); return
    if not context.args:
        await update.message.reply_text("⚠️ Format: /revoke <user_id atau @username>\nContoh: /revoke 123456789"); return
    ok, msg = await _do_revoke(context.args[0].strip(), context)
    await update.message.reply_text(msg, reply_markup=admin_keyboard() if ok else None)
