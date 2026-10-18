import asyncio

from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from admin.callbacks import admin_callback_handler, admin_message_handler, cmd_admin, cmd_backup, cmd_stats
from admin.gift import cmd_gift
from admin.vip import cmd_revoke
from auth.setup import (
    cmd_setup,
    register_telethon_handlers,
    set_ptb_bot,
    setup_agree_callback,
    setup_try_trial_callback,
    setup_continue_after_trial_callback,
    setup_code,
    setup_password,
    setup_phone,
)
from auth.states import CODE_STEP, PASSWORD_STEP, PHONE_STEP
from config import BOT_TOKEN
from database import get_conn, init_db, is_subscribed
from user.auto_block_leaver import handle_chat_member_left
from user.callbacks import user_callback_handler
from user.inputs import user_input_handler
from user.payment import payment_callback_handler
from user.qris import qris_callback_handler
from scheduler import scheduler_loop
from services.session_runner import ensure_client_running
from user.start import cmd_cancel, cmd_start


async def post_init(app):
    # Set PTB bot ke setup.py supaya bisa dipakai untuk kirim log channel
    set_ptb_bot(app.bot)

    try:
        init_db()
        print("✅ Database siap.")
    except Exception as e:
        print(f"❌ Gagal init database: {e}"); return

    # Loop latar belakang: auto backup, expire order, pengingat VIP
    app.bot_data["scheduler_task"] = asyncio.create_task(scheduler_loop(app.bot))
    print("⏱️ Scheduler berjalan (auto backup, order, pengingat).")

    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute("SELECT user_id, string_session FROM sessions")
        rows = cur.fetchall(); conn.close()
    except Exception as e:
        print(f"❌ Gagal load sessions: {e}"); return
    if not rows:
        print("ℹ️ Tidak ada session tersimpan."); return
    print(f"🔄 Memuat {len(rows)} session tersimpan...")
    for row in rows:
        user_id = row[0]
        if not is_subscribed(user_id):
            print(f"⏭️ Skip session user {user_id} (VIP tidak aktif)"); continue
        result = await ensure_client_running(user_id, app.bot)
        if result.startswith("failed"):
            print(f"⚠️ Gagal load session user {user_id}: {result}")
    print("✅ Proses load session selesai!")


async def post_shutdown(app):
    task = app.bot_data.get("scheduler_task")
    if task:
        task.cancel()


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    setup_conv = ConversationHandler(
        entry_points=[
            CommandHandler("setup", cmd_setup),
            CallbackQueryHandler(setup_agree_callback, pattern="^setup_agree$"),
            CallbackQueryHandler(setup_try_trial_callback, pattern="^setup_try_trial$"),
            CallbackQueryHandler(setup_continue_after_trial_callback, pattern="^setup_continue_after_trial$"),
        ],
        states={
            PHONE_STEP: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_phone)],
            CODE_STEP: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_code)],
            PASSWORD_STEP: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_password)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("gift", cmd_gift))
    app.add_handler(CommandHandler("revoke", cmd_revoke))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(setup_conv)
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern=r"^(menu_admin|admin_|bl_)"))
    app.add_handler(CallbackQueryHandler(payment_callback_handler, pattern=r"^pay_"))
    app.add_handler(CallbackQueryHandler(qris_callback_handler, pattern=r"^(fitur_qris|qris_)"))
    app.add_handler(CallbackQueryHandler(user_callback_handler))
    app.add_handler(MessageHandler(filters.ALL, admin_message_handler), group=2)
    # Input user saat mode menunggu (upload QRIS statis / bukti bayar)
    app.add_handler(MessageHandler(filters.ALL, user_input_handler), group=3)
    # Handler untuk auto block leaver — mendeteksi member yang keluar channel/supergroup
    app.add_handler(ChatMemberHandler(handle_chat_member_left, ChatMemberHandler.CHAT_MEMBER))
    print("🤖 Bot berjalan...")
    app.run_polling(allowed_updates=[
        "message",
        "callback_query",
        "chat_member",
    ])


if __name__ == "__main__":
    main()
