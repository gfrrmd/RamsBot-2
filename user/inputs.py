"""Router input non-command dari user (gambar QRIS / bukti bayar) saat dalam mode menunggu."""
from telegram import Update
from telegram.ext import ContextTypes

from auth.states import waiting_payment_proof, waiting_qris_upload
from user.payment import handle_proof_input
from user.qris import handle_qris_input


async def user_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, user = update.effective_message, update.effective_user
    if not msg or not user:
        return
    uid = user.id
    if msg.text and msg.text.startswith("/"):
        return
    if uid in waiting_qris_upload:
        await handle_qris_input(update, context)
    elif uid in waiting_payment_proof:
        await handle_proof_input(update, context)
