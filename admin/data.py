"""Kategori Data: info database, bersihkan data tidak penting (backup/restore/auto backup ada di menu yang sama)."""
import asyncio
import re

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup

from admin import autobackup
from database import (
    CLEAN_DAYS,
    CLEAN_KEYS,
    CLEAN_SAFE_KEYS,
    cleanup_run_many,
    get_db_info,
    vacuum_db,
)
from keyboards import data_keyboard
from ui import edit_or_send, esc, fmt_dt, header

_LABEL = {
    "orders_dead": "Pesanan gagal/kedaluwarsa/batal (> {d} hari)",
    "orders_paid": "Riwayat pesanan lunas (> {d} hari)",
    "subs_old": "Langganan expired lama (> {d} hari, tanpa session)",
    "users_idle": "User tidak aktif (> {d} hari, tanpa aktivitas)",
    "orphans": "Data yatim (sisa user yang sudah terhapus)",
}
_BTN = {
    "orders_dead": "Pesanan gagal",
    "orders_paid": "Riwayat lunas",
    "subs_old": "Langganan lama",
    "users_idle": "User tidak aktif",
    "orphans": "Data yatim",
}


def _label(key: str) -> str:
    return _LABEL[key].format(d=CLEAN_DAYS.get(key, ""))


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
        f"Auto backup: {'ON ✅' if ab_on else 'OFF ❌'}\n"
        f"Backup terakhir: {esc(fmt_dt(last)) if last else '—'}\n\n"
        "Pilih menu di bawah:"
    )


def _clean_text(prev: dict) -> str:
    lines = [header("🧹", "Bersihkan Data"), "Data tidak penting yang bisa dihapus saat ini:"]
    for k in CLEAN_KEYS:
        lines.append(f"{_label(k)}: {prev[k]}")
    lines += [
        "",
        "Tidak pernah dihapus: session user, VIP aktif, pesanan yang masih menunggu, paket, pengaturan, "
        "blacklist, dan user yang pernah memakai trial.",
        "",
        "Backup otomatis dikirim ke kamu sebelum data dihapus. "
        "Menghapus riwayat lunas akan mengurangi total pendapatan di statistik, jadi tidak ikut tombol Bersihkan Semua.",
    ]
    return "\n".join(lines)


def _clean_keyboard(prev: dict) -> InlineKeyboardMarkup:
    rows = []
    safe_total = prev.get("_all", 0)
    if safe_total:
        rows.append([Btn(f"🧹 Bersihkan Semua ({safe_total})", callback_data="admin_clean_ask_all")])
    pair = []
    for k in CLEAN_KEYS:
        if prev[k]:
            pair.append(Btn(f"{_BTN[k]} ({prev[k]})", callback_data=f"admin_clean_ask_{k}"))
    rows += [pair[i:i + 2] for i in range(0, len(pair), 2)]
    rows.append([Btn("🔙 Data", callback_data="admin_data")])
    return InlineKeyboardMarkup(rows)


def _simulate(keys) -> dict:
    """Jumlah pasti yang akan terhapus (simulasi di transaksi yang di-rollback)."""
    return cleanup_run_many(list(keys), dry_run=True)


async def show_clean(query):
    prev = await asyncio.to_thread(_simulate, CLEAN_KEYS)
    prev_all = await asyncio.to_thread(_simulate, CLEAN_SAFE_KEYS)
    prev = dict(prev, _all=sum(prev_all.values()))
    if not sum(v for k, v in prev.items() if k != "_all"):
        text = _clean_text(prev) + "\n\n✅ Tidak ada data yang perlu dibersihkan."
    else:
        text = _clean_text(prev)
    await edit_or_send(query, text, _clean_keyboard(prev))


async def handle_callback(query, context, data: str) -> bool:
    if data == "admin_data":
        await edit_or_send(query, build_data_text(), data_keyboard())
        return True

    if data == "admin_clean":
        await show_clean(query)
        return True

    m = re.fullmatch(r"admin_clean_ask_([a-z_]+)", data)
    if m:
        key = m.group(1)
        keys = CLEAN_SAFE_KEYS if key == "all" else [key]
        if key != "all" and key not in CLEAN_KEYS:
            return True
        prev = await asyncio.to_thread(_simulate, keys)
        items = "\n".join(f"{_label(k)}: {prev[k]}" for k in keys)
        await edit_or_send(
            query,
            f"{header('⚠️', 'Konfirmasi Hapus')}\nData berikut akan dihapus permanen:\n\n{items}\n\n"
            "Backup akan dikirim dulu. Jika backup gagal, penghapusan dibatalkan.",
            InlineKeyboardMarkup([[Btn("✅ Ya, hapus", callback_data=f"admin_clean_do_{key}"),
                                   Btn("❌ Batal", callback_data="admin_clean")]]),
        )
        return True

    m = re.fullmatch(r"admin_clean_do_([a-z_]+)", data)
    if m:
        key = m.group(1)
        keys = CLEAN_SAFE_KEYS if key == "all" else [key]
        if key != "all" and key not in CLEAN_KEYS:
            return True
        await edit_or_send(query, "⏳ Membuat backup sebelum menghapus...")
        ok, info = await autobackup.run_backup(context.bot, "now")
        if not ok:
            await edit_or_send(query, f"❌ Backup gagal, data tidak dihapus.\n{esc(info[:200])}",
                               InlineKeyboardMarkup([[Btn("🔙 Data", callback_data="admin_data")]]))
            return True
        result = await asyncio.to_thread(cleanup_run_many, keys)
        try:
            await asyncio.to_thread(vacuum_db)
        except Exception:
            pass
        lines = "\n".join(f"{_label(k)}: {n} dihapus" for k, n in result.items())
        await edit_or_send(
            query,
            f"{header('✅', 'Pembersihan Selesai')}\n{lines}\n\nTotal: {sum(result.values())} baris dihapus.\n"
            "Backup sebelum pembersihan sudah dikirim ke kamu.",
            InlineKeyboardMarkup([[Btn("🗄️ Data", callback_data="admin_data")]]),
        )
        return True

    return False
