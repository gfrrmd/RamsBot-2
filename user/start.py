from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from auth.states import clear_user_state
from database import upsert_user
from keyboards import main_keyboard
from ui import build_home_text


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = update.effective_user
    clear_user_state(uid)
    upsert_user(uid, user.username, user.full_name)
    if context.args and context.args[0].startswith("pay_") and context.args[0][4:].isdigit():   # deep link Mini App
        from database import get_order                       # import lokal: hindari circular import
        from user.payment import begin_proof
        await begin_proof(update.message, uid, get_order(int(context.args[0][4:])))
        return ConversationHandler.END
    if context.args and context.args[0] == "setup":          # deep link dari Mini App
        await update.message.reply_text(
            "✨ Tekan tombol di bawah untuk memulai setup session akun Telegram kamu.",
            reply_markup=InlineKeyboardMarkup([[Btn("✨ Setup Bot", callback_data="menu_setup")], [Btn("🏠 Menu Utama", callback_data="menu_back")]]))
        return ConversationHandler.END
    await update.message.reply_text(build_home_text(user), parse_mode=ParseMode.HTML, reply_markup=main_keyboard(uid))
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    clear_user_state(uid)
    await update.message.reply_text("❌ Dibatalkan. Kembali ke menu utama.", reply_markup=main_keyboard(uid))
    return ConversationHandler.END
