from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup

from config import ADMIN_ID
from database import get_auto_dl_view_once, has_used_trial

HOME = Btn("🏠 Menu Utama", callback_data="menu_back")


# ── User ──────────────────────────────────────────────────────────────────────

def main_keyboard(uid):
    rows = [
        [Btn("✨ Setup Bot", callback_data="menu_setup")],
        [Btn("🎯 Fitur VIP", callback_data="menu_fitur"), Btn("👤 Status Akun", callback_data="menu_subscription")],
        [Btn("📖 Panduan", callback_data="menu_beli"), Btn("💎 Beli VIP", callback_data="pay_menu")],
    ]
    if uid == ADMIN_ID:
        rows.append([Btn("🛠️ Panel Admin", callback_data="menu_admin")])
    return InlineKeyboardMarkup(rows)


def tos_keyboard():
    return InlineKeyboardMarkup([
        [Btn("✅ Saya Setuju", callback_data="setup_agree")],
        [Btn("🔙 Kembali", callback_data="menu_back"), Btn("❌ Tutup", callback_data="tos_close")],
    ])


def not_subscribed_keyboard(uid):
    rows = [[Btn("💎 Beli VIP", callback_data="pay_menu")]]
    if not has_used_trial(uid):
        rows.append([Btn("🎟️ Coba Trial Gratis", callback_data="setup_try_trial")])
    rows.append([Btn("📖 Panduan", callback_data="menu_beli")])
    rows.append([Btn("🔙 Kembali", callback_data="menu_back")])
    return InlineKeyboardMarkup(rows)


def trial_activated_keyboard():
    return InlineKeyboardMarkup([
        [Btn("➡️ Lanjut Setup", callback_data="setup_continue_after_trial")],
    ])


def fitur_vip_keyboard():
    return InlineKeyboardMarkup([
        [Btn("⏱️ Media Timer", callback_data="fitur_timer"), Btn("📣 Channel/Grup", callback_data="fitur_copy")],
        [Btn("🎥 Story", callback_data="fitur_story"), Btn("📢 Broadcast", callback_data="fitur_broadcast")],
        [Btn("💳 QRIS Dinamis", callback_data="fitur_qris"), Btn("✅ Auto Approve", callback_data="fitur_acceptall")],
        [Btn("🔒 Auto Block Leaver", callback_data="fitur_autoblock"), Btn("🏓 Ping", callback_data="fitur_ping")],
        [HOME],
    ])


def broadcast_keyboard():
    return InlineKeyboardMarkup([
        [Btn("⛔ Blacklist Grup", callback_data="bc_blacklist_menu")],
        [Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")],
    ])


def bc_blacklist_keyboard():
    return InlineKeyboardMarkup([
        [Btn("📋 List Blacklist", callback_data="bc_bl_list")],
        [Btn("🔙 Kembali ke Broadcast", callback_data="fitur_broadcast")],
    ])


def beli_keyboard():
    return InlineKeyboardMarkup([
        [Btn("💎 Beli VIP", callback_data="pay_menu")],
        [Btn("🔙 Kembali", callback_data="menu_back")],
    ])


def timer_keyboard(uid):
    auto_on = get_auto_dl_view_once(uid)
    return InlineKeyboardMarkup([
        [Btn(f"⏱️ Auto DL: {'ON ✅' if auto_on else 'OFF ❌'}", callback_data="vip_toggle_auto_dl")],
        [Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")],
    ])


def back_to_fitur_keyboard():
    return InlineKeyboardMarkup([[Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")]])


def qris_keyboard(has_qris: bool):
    rows = [[Btn("🔄 Ganti QRIS Statis" if has_qris else "📤 Upload QRIS Statis", callback_data="qris_upload")]]
    if has_qris:
        rows.append([Btn("👁️ Lihat QRIS Tersimpan", callback_data="qris_view"), Btn("🗑️ Hapus", callback_data="qris_delete")])
    rows.append([Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")])
    return InlineKeyboardMarkup(rows)


# ── Admin ─────────────────────────────────────────────────────────────────────

def admin_keyboard(pending: int = 0):
    pay_label = f"💳 Pembayaran{f' ({pending})' if pending else ''}"
    return InlineKeyboardMarkup([
        [Btn("📊 Statistik", callback_data="admin_stats"), Btn(pay_label, callback_data="admin_pay")],
        [Btn("👑 List VIP", callback_data="admin_viplist_0"), Btn("🔎 Cek User", callback_data="admin_finduser")],
        [Btn("🎁 Gift VIP", callback_data="admin_gift"), Btn("🚫 Revoke VIP", callback_data="admin_revoke")],
        [Btn("📢 Pengumuman", callback_data="admin_announce"), Btn("🔒 Blacklist", callback_data="admin_blacklist")],
        [Btn("💾 Auto Backup", callback_data="admin_autobackup")],
        [Btn("📦 Backup DB", callback_data="admin_backup"), Btn("♻️ Restore DB", callback_data="admin_restore")],
        [HOME],
    ])


def admin_back_keyboard():
    return InlineKeyboardMarkup([[Btn("🔙 Panel Admin", callback_data="menu_admin")]])


def blacklist_keyboard():
    return InlineKeyboardMarkup([
        [Btn("➕ Tambah", callback_data="bl_add"), Btn("➖ Hapus", callback_data="bl_remove")],
        [Btn("📋 Lihat List", callback_data="bl_list")],
        [Btn("🔙 Kembali ke Admin", callback_data="menu_admin")],
    ])


def order_admin_keyboard(order_id: int):
    """Tombol di notifikasi bukti bayar untuk admin."""
    return InlineKeyboardMarkup([
        [Btn("✅ Approve", callback_data=f"admin_ord_ok_{order_id}"), Btn("❌ Tolak", callback_data=f"admin_ord_no_{order_id}")],
    ])
