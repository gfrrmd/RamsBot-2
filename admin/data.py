"""Kategori Data: info database dan pembersihan data tidak penting (backup/restore/auto backup ada di menu yang sama)."""
import asyncio
import re

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup

from admin import autobackup
from client_manager import active_clients, stop_client_for_user
from database import CLEAN_KEYS, clean_label, cleanup_all, get_db_info, vacuum_db
from keyboards import data_keyboard
from ui import edit_or_send, esc, fmt_dt, header


def _size(n) -> str:
    if n is None:
        return "—"
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def build_data_text() -> str:
    i = get_db_info()
    ab_on = autobackup.is_enabled()
    last = autobackup.get_setting("ab_last_at")
    return (
        f"{header('🗄️', 'Data')}\n"
        f"Ukuran database: {_size(i['size'])}\n"
        f"User: {i['users']}\n"
        f"Session: {i['sessions']}\n"
        f"Langganan: {i['subscriptions']}\n"
        f"Pesanan: {i['orders']}\n"
        f"QRIS user: {i['user_qris']}\n"
        f"Auto backup: {'ON' if ab_on else 'OFF'}\n"
        f"Backup terakhir: {esc(fmt_dt(last)) if last else '—'}\n\n"
        "Pilih menu di bawah:"
    )


def _counts_text(prev: dict) -> str:
    return "\n".join(f"{clean_label(k)}: {prev[k]}" for k in CLEAN_KEYS)


_KEPT = (
    "Yang dipertahankan: akun admin, VIP dan trial yang masih aktif, user dengan pesanan yang masih "
    "menunggu pembayaran, paket, pengaturan bot, dan blacklist channel."
)


async def show_clean(query):
    prev = await asyncio.to_thread(cleanup_all, True)
    total = sum(prev[k] for k in CLEAN_KEYS)
    lines = [
        header("🧹", "Bersihkan Data").rstrip(),
        "Data berikut akan dihapus, tanpa batas waktu:",
        "- User yang belum pernah membeli, VIP expired atau dicabut, dan pemakai trial",
        "- Riwayat pesanan milik user tersebut, serta pesanan gagal, batal, dan kedaluwarsa",
        "- Session, QRIS, pengaturan, blacklist broadcast, auto block, dan token VIP mereka",
        "- Voucher dan kode promo yang sudah habis atau kedaluwarsa",
        "",
        "Jumlah saat ini:",
        _counts_text(prev),
        "",
        _KEPT,
        "",
        "Pemakai trial yang datanya dihapus bisa memakai trial lagi. "
        "Statistik pendapatan akan berkurang sesuai pesanan lunas yang dihapus. "
        "Backup dikirim otomatis sebelum data dihapus.",
    ]
    if not total:
        lines += ["", "Tidak ada data yang perlu dibersihkan."]
        kb = [[Btn("🔙 Data", callback_data="admin_data")]]
    else:
        kb = [[Btn(f"🧹 Bersihkan Sekarang ({total})", callback_data="admin_clean_ask")],
              [Btn("🔙 Data", callback_data="admin_data")]]
    await edit_or_send(query, "\n".join(lines), InlineKeyboardMarkup(kb))


async def handle_callback(query, context, data: str) -> bool:
    if data == "admin_data":
        await edit_or_send(query, build_data_text(), data_keyboard())
        return True

    if data == "admin_clean":
        await show_clean(query)
        return True

    if data == "admin_clean_ask":
        prev = await asyncio.to_thread(cleanup_all, True)
        await edit_or_send(
            query,
            f"{header('⚠️', 'Konfirmasi Hapus').replace('<b> ', '<b>')}Data berikut akan dihapus permanen:\n\n"
            f"{_counts_text(prev)}\n\n"
            "Backup dikirim dulu. Jika backup gagal, penghapusan dibatalkan.",
            InlineKeyboardMarkup([[Btn("✅ Ya, hapus", callback_data="admin_clean_do"),
                                   Btn("❌ Batal", callback_data="admin_clean")]]),
        )
        return True

    if data == "admin_clean_do":
        await edit_or_send(query, "Membuat backup sebelum menghapus...")
        ok, info = await autobackup.run_backup(context.bot, "now")
        if not ok:
            await edit_or_send(query, f"Backup gagal, data tidak dihapus.\n{esc(info[:200])}",
                               InlineKeyboardMarkup([[Btn("🗄️ Data", callback_data="admin_data")]]))
            return True
        result = await asyncio.to_thread(cleanup_all)
        for uid in result.get("user_ids", []):          # hentikan client Telethon user yang datanya dihapus
            if uid in active_clients:
                try:
                    await stop_client_for_user(uid)
                except Exception:
                    pass
        try:
            await asyncio.to_thread(vacuum_db)
        except Exception:
            pass
        total = sum(result[k] for k in CLEAN_KEYS)
        await edit_or_send(
            query,
            f"{header('✅', 'Pembersihan Selesai').replace('<b> ', '<b>')}{_counts_text(result)}\n\n"
            f"Total: {total} baris dihapus.\nBackup sebelum pembersihan sudah dikirim ke kamu.",
            InlineKeyboardMarkup([[Btn("🗄️ Data", callback_data="admin_data")]]),
        )
        return True

    return False
