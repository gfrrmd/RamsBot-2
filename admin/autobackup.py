"""Auto backup database: pengaturan, eksekusi, dan tampilan menu admin."""
import asyncio
import gzip
import io
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.constants import ParseMode

from admin.backup import build_backup_sql
from config import ADMIN_ID, BACKUP_CHANNEL_ID
from database import get_setting, set_setting
from ui import esc, fmt_dt, header

INTERVAL_CHOICES = [(6, "6 jam"), (12, "12 jam"), (24, "24 jam"), (72, "3 hari"), (168, "7 hari")]
MAX_UPLOAD = 49 * 1024 * 1024        # batas upload bot Telegram ±50 MB
RETRY_AFTER_FAIL_MIN = 30


# ── Pengaturan ────────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    return get_setting("ab_enabled", "1") == "1"


def get_interval_hours() -> int:
    try:
        return max(1, int(get_setting("ab_interval_h", "24")))
    except ValueError:
        return 24


def get_channel_id() -> int:
    raw = get_setting("ab_channel", None)
    if raw is None:
        return BACKUP_CHANNEL_ID
    try:
        return int(raw)
    except ValueError:
        return 0


def _interval_label(h: int) -> str:
    return dict(INTERVAL_CHOICES).get(h, f"{h} jam")


def is_due(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if not is_enabled():
        return False
    last_attempt = get_setting("ab_last_attempt")
    if last_attempt:
        try:
            if now - datetime.fromisoformat(last_attempt) < timedelta(minutes=RETRY_AFTER_FAIL_MIN) \
                    and get_setting("ab_last_status", "") != "ok":
                return False
        except ValueError:
            pass
    last_ok = get_setting("ab_last_at")
    if not last_ok:
        return True
    try:
        return now - datetime.fromisoformat(last_ok) >= timedelta(hours=get_interval_hours())
    except ValueError:
        return True


# ── Eksekusi ──────────────────────────────────────────────────────────────────

async def run_backup(bot, reason: str = "auto") -> tuple[bool, str]:
    """
    Buat backup lalu kirim ke admin (+ channel jika diatur).
    reason: 'auto' (terjadwal) | 'now' (tombol "Backup Sekarang"). File dikompres .sql.gz.
    """
    now = datetime.now()
    set_setting("ab_last_attempt", now.isoformat())
    try:
        sql_bytes, counts = await asyncio.to_thread(build_backup_sql)
        stamp = now.strftime("%Y%m%d_%H%M%S")
        data = await asyncio.to_thread(gzip.compress, sql_bytes, 6)
        fname = f"ramsbot_backup_{stamp}.sql.gz"
        if len(data) > MAX_UPLOAD:
            data = await asyncio.to_thread(gzip.compress, sql_bytes, 9)
        if len(data) > MAX_UPLOAD:
            raise RuntimeError(f"ukuran backup {len(data) / 1048576:.1f} MB melebihi batas upload Telegram")

        total_rows = sum(counts.values())
        caption = (
            f"💾 <b>{'Auto Backup' if reason == 'auto' else 'Backup Manual'}</b>\n"
            f"🕒 {esc(fmt_dt(now))}\n"
            f"🗂️ {len(counts)} tabel - {total_rows} baris - {len(data) / 1024:.1f} KB\n"
            f"♻️ Restore: kirim file ini lewat Panel Admin → Restore DB"
        )
        targets = [ADMIN_ID]
        ch = get_channel_id()
        if ch:
            targets.append(ch)
        errors = []
        for chat_id in targets:
            try:
                await bot.send_document(chat_id=chat_id, document=io.BytesIO(data), filename=fname,
                                        caption=caption, parse_mode=ParseMode.HTML)
            except Exception as e:
                errors.append(f"{chat_id}: {e}")
        if len(errors) == len(targets):
            raise RuntimeError("; ".join(errors))
        set_setting("ab_last_at", now.isoformat())
        set_setting("ab_last_status", "ok")
        set_setting("ab_last_info", f"{fname} ({len(data) / 1024:.1f} KB)")
        note = f"\n⚠️ Sebagian tujuan gagal: {errors[0]}" if errors else ""
        return True, f"{fname}{note}"
    except Exception as e:
        set_setting("ab_last_status", f"gagal: {e}")
        try:
            if reason == "auto":
                await bot.send_message(ADMIN_ID, f"⚠️ <b>Auto Backup gagal</b>\n<code>{esc(str(e)[:300])}</code>\n"
                                       f"Akan dicoba lagi dalam {RETRY_AFTER_FAIL_MIN} menit.", parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return False, str(e)


# ── Tampilan ──────────────────────────────────────────────────────────────────

def build_autobackup_text() -> str:
    on = is_enabled()
    ch = get_channel_id()
    last_at = get_setting("ab_last_at")
    status = get_setting("ab_last_status", "—")
    nxt = "—"
    if on and last_at:
        try:
            nxt = fmt_dt(datetime.fromisoformat(last_at) + timedelta(hours=get_interval_hours()))
        except ValueError:
            pass
    elif on:
        nxt = "segera"
    tujuan = "PM Admin" + (f" + channel <code>{ch}</code>" if ch else "")
    terakhir = esc(fmt_dt(last_at)) if last_at else "—"
    hasil = esc(status if status == "ok" else status[:80])
    return (
        f"{header('💾', 'Auto Backup')}\n"
        f"Status: {'ON ✅' if on else 'OFF ❌'}\n"
        f"Interval: setiap {_interval_label(get_interval_hours())}\n"
        f"Tujuan: {tujuan}\n"
        f"Terakhir: {terakhir}\n"
        f"Berikutnya: {esc(nxt)}\n"
        f"Hasil: {hasil}\n\n"
        "File dikirim sebagai <code>.sql.gz</code> ke Telegram sehingga aman walau server Railway "
        "di-redeploy.\n\n"
        "Catatan: backup berisi data session, jangan kirim ke channel publik."
    )


def autobackup_keyboard() -> InlineKeyboardMarkup:
    on = is_enabled()
    cur = get_interval_hours()
    interval_row = [Btn(("• " if h == cur else "") + label, callback_data=f"admin_ab_int_{h}") for h, label in INTERVAL_CHOICES]
    return InlineKeyboardMarkup([
        [Btn(f"Auto Backup: {'ON ✅' if on else 'OFF ❌'}", callback_data="admin_ab_toggle")],
        interval_row[:3],
        interval_row[3:],
        [Btn("📡 Atur Channel Tujuan", callback_data="admin_ab_channel"), Btn("📦 Backup Sekarang", callback_data="admin_ab_now")],
        [Btn("🔙 Panel Admin", callback_data="menu_admin")],
    ])
