from telegram import Update
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
    await update.message.reply_text(build_home_text(user), parse_mode=ParseMode.HTML, reply_markup=main_keyboard(uid))
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    clear_user_state(uid)
    await update.message.reply_text("❌ Dibatalkan. Kembali ke menu utama.", reply_markup=main_keyboard(uid))
    return ConversationHandler.END
