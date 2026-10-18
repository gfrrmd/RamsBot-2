import gzip
import io
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from admin import panel, payments
from admin.backup import _do_backup, _split_sql_statements, fix_sequences, maybe_gunzip
from admin.blacklist import build_blacklist_text
from admin.gift import _do_gift
from admin.vip import _do_revoke
from auth.states import admin_state, waiting_gift, waiting_restore, waiting_revoke
from config import ADMIN_ID
from database import blacklist_add, blacklist_remove
from keyboards import admin_keyboard, blacklist_keyboard
from ui import edit_or_send, header

waiting_bl_add: set[int] = set()
waiting_bl_remove: set[int] = set()

HTML = ParseMode.HTML


def _clear_admin_waits(uid: int):
    for s in (waiting_gift, waiting_revoke, waiting_restore, waiting_bl_add, waiting_bl_remove):
        s.discard(uid)
    admin_state.pop(uid, None)


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    if uid != ADMIN_ID:
        await query.answer()
        return
    if not (data == "menu_admin" or data.startswith("admin_") or data.startswith("bl_")):
        return
    await query.answer()
    if data != "admin_ann_go":          # draft pengumuman harus tetap hidup saat konfirmasi
        _clear_admin_waits(uid)

    if data == "menu_admin":
        text, waiting = panel.admin_home_text()
        await edit_or_send(query, text, admin_keyboard(waiting))
        return
    if data == "admin_backup":
        await edit_or_send(query, "⏳ Sedang membuat backup...")
        try:
            sql_bytes = await _do_backup(context)
            fname = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
            await context.bot.send_document(chat_id=uid, document=sql_bytes, filename=fname, caption="✅ Backup database berhasil!")
            await edit_or_send(query, "✅ Backup selesai!", admin_keyboard())
        except Exception as e:
            await edit_or_send(query, f"❌ Backup gagal: {e}", admin_keyboard())
        return
    if data == "admin_restore":
        waiting_restore.add(uid)
        await edit_or_send(query, f"{header('♻️', 'Restore Database')}\nKirim file <code>.sql</code> atau <code>.sql.gz</code> backup kamu sekarang.\nAtau ketik /cancel untuk batal.")
        return
    if data == "admin_gift":
        waiting_gift.add(uid)
        await edit_or_send(query, f"{header('🎁', 'Gift VIP')}\nKirim: <code>&lt;user_id atau @username&gt; &lt;jumlah_hari&gt;</code>\nContoh: <code>123456789 30</code>\n\nAtau ketik /cancel untuk batal.")
        return
    if data == "admin_revoke":
        waiting_revoke.add(uid)
        await edit_or_send(query, f"{header('🚫', 'Revoke VIP')}\nKirim user ID atau @username yang ingin dicabut VIP-nya.\nAtau ketik /cancel untuk batal.")
        return
    if data == "admin_blacklist":
        await edit_or_send(query, f"{header('🔒', 'Blacklist Channel')}\nKelola daftar channel/grup yang diblokir dari <code>.copy</code>", blacklist_keyboard())
        return
    if data == "bl_add":
        waiting_bl_add.add(uid)
        await edit_or_send(query, f"{header('➕', 'Tambah ke Blacklist')}\nKirim username atau ID channel.\nFormat: <code>@username</code> atau <code>-100xxxxxxxxxx</code>\nBisa tambah catatan: <code>@username alasan</code>\n\nKetik /cancel untuk batal.")
        return
    if data == "bl_remove":
        waiting_bl_remove.add(uid)
        await edit_or_send(query, f"{header('➖', 'Hapus dari Blacklist')}\nKirim username atau ID channel yang ingin dihapus.\nKetik /cancel untuk batal.")
        return
    if data == "bl_list":
        await edit_or_send(query, build_blacklist_text(), blacklist_keyboard())
        return

    # Modul baru
    if await payments.handle_callback(query, context, data):
        return
    await panel.handle_callback(query, context, data)


async def admin_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.effective_message:
        return
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        return
    msg = update.effective_message
    in_any = (uid in waiting_gift or uid in waiting_revoke or uid in waiting_restore
              or uid in waiting_bl_add or uid in waiting_bl_remove or uid in admin_state)
    if not in_any:
        return

    if uid in waiting_restore:
        waiting_restore.discard(uid)
        if not msg.document:
            await msg.reply_text("❌ Kirim file .sql / .sql.gz yang valid, atau ketik /cancel untuk batal.")
            waiting_restore.add(uid)
            return
        file = await context.bot.get_file(msg.document.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        conn = None
        try:
            sql = maybe_gunzip(buf.getvalue()).decode("utf-8")
            from database import get_conn
            conn = get_conn()
            cur = conn.cursor()
            stmts = _split_sql_statements(sql)
            for stmt in stmts:
                cur.execute(stmt)
            conn.commit()
            fix_sequences(conn)
            await msg.reply_text(f"✅ Restore berhasil! ({len(stmts)} statement dijalankan)", reply_markup=admin_keyboard())
        except Exception as e:
            if conn:
                conn.rollback()
            await msg.reply_text(f"❌ Restore gagal: {e}", reply_markup=admin_keyboard())
        finally:
            if conn:
                conn.close()
        return

    if uid in waiting_gift:
        waiting_gift.discard(uid)
        parts = (msg.text.strip() if msg.text else "").split()
        if not parts:
            await msg.reply_text("❌ Input tidak valid. Ketik /cancel untuk batal.")
            waiting_gift.add(uid)
            return
        days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 30
        ok, text = await _do_gift(parts[0], days, context)
        await msg.reply_text(text, reply_markup=admin_keyboard())
        return

    if uid in waiting_revoke:
        waiting_revoke.discard(uid)
        text = msg.text.strip() if msg.text else ""
        if not text:
            await msg.reply_text("❌ Input tidak valid. Ketik /cancel untuk batal.")
            waiting_revoke.add(uid)
            return
        ok, text = await _do_revoke(text, context)
        await msg.reply_text(text, reply_markup=admin_keyboard())
        return

    if uid in waiting_bl_add:
        waiting_bl_add.discard(uid)
        text = msg.text.strip() if msg.text else ""
        parts = text.split(maxsplit=1)
        if not parts:
            await msg.reply_text("❌ Input tidak valid. Ketik /cancel untuk batal.")
            waiting_bl_add.add(uid)
            return
        identifier = parts[0].lstrip("@")
        note = parts[1] if len(parts) > 1 else ""
        ok = blacklist_add(identifier, note)
        await msg.reply_text(f"✅ <code>{identifier}</code> berhasil ditambahkan ke blacklist." if ok else f"⚠️ <code>{identifier}</code> sudah ada di blacklist.",
                             parse_mode=HTML, reply_markup=blacklist_keyboard())
        return

    if uid in waiting_bl_remove:
        waiting_bl_remove.discard(uid)
        identifier = (msg.text.strip() if msg.text else "").lstrip("@")
        if not identifier:
            await msg.reply_text("❌ Input tidak valid. Ketik /cancel untuk batal.")
            waiting_bl_remove.add(uid)
            return
        ok = blacklist_remove(identifier)
        await msg.reply_text(f"✅ <code>{identifier}</code> berhasil dihapus dari blacklist." if ok else f"❌ <code>{identifier}</code> tidak ditemukan di blacklist.",
                             parse_mode=HTML, reply_markup=blacklist_keyboard())
        return

    state = admin_state.get(uid)
    if state:
        if await payments.handle_state_message(update, context, state):
            return
        await panel.handle_state_message(update, context, state)


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Kamu tidak memiliki izin.")
        return
    text, waiting = panel.admin_home_text()
    await update.message.reply_text(text, parse_mode=HTML, reply_markup=admin_keyboard(waiting))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Kamu tidak memiliki izin.")
        return
    await update.message.reply_text(panel.build_stats_text(), parse_mode=HTML)


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Kamu tidak memiliki izin.")
        return
    from admin import autobackup
    note = await update.message.reply_text("⏳ Membuat backup...")
    ok, info = await autobackup.run_backup(context.bot, "now")
    await note.edit_text("✅ Backup terkirim." if ok else f"❌ Backup gagal: {info}")
