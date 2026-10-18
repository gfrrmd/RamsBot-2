"""Loop latar belakang: auto backup, kedaluwarsa order, pengingat & penghentian VIP habis."""
import asyncio
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.constants import ParseMode

from admin import autobackup
from client_manager import active_clients, stop_client_for_user
from database import expire_stale_orders, get_setting, get_subs_for_reminder, set_reminder_stage
from ui import esc, fmt_dt

TICK_SECONDS = 60
REMINDER_EVERY_TICKS = 10        # cek pengingat tiap ±10 menit

_RENEW_KB = InlineKeyboardMarkup([[Btn("💎 Perpanjang Sekarang", callback_data="pay_menu")]])


def order_expire_minutes() -> int:
    try:
        return max(5, int(get_setting("pay_expire_min", "60")))
    except ValueError:
        return 60


async def _expire_orders(bot):
    for o in expire_stale_orders(order_expire_minutes()):
        try:
            await bot.send_message(
                o["user_id"],
                f"⌛ <b>Pesanan #{o['id']} kedaluwarsa</b>\nBatas waktu pembayaran habis. "
                "Jika sudah terlanjur membayar, hubungi admin dengan bukti transfer.\n"
                "Untuk memesan lagi, tekan tombol di bawah.",
                parse_mode=ParseMode.HTML, reply_markup=_RENEW_KB,
            )
        except Exception:
            pass


async def _subscription_reminders(bot):
    now = datetime.now()
    for s in get_subs_for_reminder():
        try:
            exp = datetime.fromisoformat(s["expired_at"])
        except Exception:
            continue
        uid, stage, left = s["user_id"], s["stage"], exp - now

        if left <= timedelta(0):                                   # sudah habis
            if uid in active_clients:
                await stop_client_for_user(uid)
            if s["plan"] == "vip":
                try:
                    await bot.send_message(
                        uid, "⛔ <b>VIP kamu telah berakhir</b>\nFitur bot dihentikan sementara. "
                        "Perpanjang sekarang — session kamu tetap tersimpan dan langsung aktif lagi setelah pembayaran.",
                        parse_mode=ParseMode.HTML, reply_markup=_RENEW_KB)
                except Exception:
                    pass
            set_reminder_stage(uid, 3)
            continue

        if s["plan"] != "vip":
            continue
        new_stage = None
        if left <= timedelta(days=1) and stage < 2:
            new_stage = 2
        elif left <= timedelta(days=3) and stage < 1:
            new_stage = 1
        if new_stage:
            try:
                await bot.send_message(
                    uid, f"⏰ <b>VIP kamu segera berakhir</b>\nBerakhir pada <b>{esc(fmt_dt(exp))}</b>. "
                    "Perpanjang sekarang agar fitur tidak terputus — sisa hari otomatis ditambahkan.",
                    parse_mode=ParseMode.HTML, reply_markup=_RENEW_KB)
            except Exception:
                pass
            set_reminder_stage(uid, new_stage)


async def scheduler_loop(bot):
    await asyncio.sleep(20)          # beri waktu bot & session selesai start
    tick = 0
    while True:
        try:
            if autobackup.is_due():
                ok, info = await autobackup.run_backup(bot, "auto")
                print(f"[scheduler] auto backup: {'OK' if ok else 'GAGAL'} — {info}")
        except Exception as e:
            print(f"[scheduler] auto backup error: {e}")
        try:
            await _expire_orders(bot)
        except Exception as e:
            print(f"[scheduler] expire orders error: {e}")
        try:
            if tick % REMINDER_EVERY_TICKS == 0:
                await _subscription_reminders(bot)
        except Exception as e:
            print(f"[scheduler] reminder error: {e}")
        tick += 1
        await asyncio.sleep(TICK_SECONDS)
