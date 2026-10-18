"""Helper tampilan: format teks HTML, tanggal WIB, dan pengiriman/edit pesan yang aman."""
import html
from datetime import datetime, timedelta, timezone

from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

from client_manager import active_clients, _start_time
from config import BOT_NAME
from database import get_subscription_info

WIB = timezone(timedelta(hours=7))
_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


# ── Format ────────────────────────────────────────────────────────────────────

def esc(v) -> str:
    return html.escape("—" if v is None or v == "" else str(v), quote=False)


def rp(n) -> str:
    return "Rp " + f"{int(n):,}".replace(",", ".")


def _parse(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(v)
    except Exception:
        return None


def to_wib(v) -> datetime | None:
    """Datetime naive dianggap UTC (konvensi database) -> WIB."""
    dt = _parse(v)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(WIB)


def fmt_date(v) -> str:
    d = to_wib(v)
    return f"{d.day:02d} {_BULAN[d.month - 1]} {d.year}" if d else "—"


def fmt_dt(v) -> str:
    d = to_wib(v)
    return f"{d.day:02d} {_BULAN[d.month - 1]} {d.year}, {d:%H:%M} WIB" if d else "—"


def fmt_remaining(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "habis"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d >= 1:
        return f"{d} hari" + (f" {h} jam" if d < 3 and h else "")
    if h >= 1:
        return f"{h} jam {m} mnt"
    return f"{max(m, 1)} menit"


def header(emoji: str, title: str) -> str:
    """Judul tebal sederhana (tanpa garis pemisah)."""
    return "<b>" + emoji + " " + esc(title) + "</b>\n"


def kv(label: str, value, width: int = 0) -> str:
    """Baris data rapi: 'Label: nilai' (width diabaikan, dipertahankan demi kompatibilitas)."""
    return f"{label}: {value}"


# ── Status langganan ──────────────────────────────────────────────────────────

def get_sub_state(uid: int) -> dict:
    """state: none | active | expired | revoked ; plan: vip | trial."""
    row = get_subscription_info(uid)
    if not row:
        return {"state": "none", "plan": None, "expired": None, "remaining": None}
    _paid, expired_at, is_active, plan = row
    exp = _parse(expired_at)
    now = datetime.now()
    if not is_active:
        state = "revoked"
    elif exp is None or exp <= now:
        state = "expired"
    else:
        state = "active"
    return {"state": state, "plan": plan, "expired": exp, "remaining": (exp - now) if exp else None}


def sub_badge(uid: int) -> str:
    s = get_sub_state(uid)
    if s["state"] == "active":
        label = "Trial 🎟️" if s["plan"] == "trial" else "VIP 💎"
        return f"{label} (sisa {fmt_remaining(s['remaining'])})"
    if s["state"] == "expired":
        return "⚠️ Expired"
    if s["state"] == "revoked":
        return "🚫 Dicabut"
    return "Belum berlangganan"


def session_badge(uid: int) -> str:
    c = active_clients.get(uid)
    return "Aktif ✅" if c and c.is_connected() else "Tidak aktif ❌"


def uptime_str(uid: int) -> str:
    import time
    start = _start_time.get(uid)
    if start is None:
        return "—"
    e = int(time.monotonic() - start)
    return f"{e // 3600:02d}:{(e % 3600) // 60:02d}:{e % 60:02d}"


def build_home_text(user) -> str:
    """Teks sapaan /start — sama seperti RamsBot asli."""
    first = esc(user.first_name or "Kamu")
    return (
        f"Halo, {first}! 👋\n"
        "Aku adalah Bot Telegram pribadi dengan berbagai fitur eksklusif. ✨\n\n"
        "Dengan bot ini kamu bisa <b>Download Media Timer</b> 📥, <b>Download Media Channel Private</b> 📣, "
        "<b>Download Story</b> 🎥, <b>Broadcast Pesan</b> 📢, <b>QRIS Dinamis</b> 💳, dan masih banyak lagi 🚀\n\n"
        "👇 Pilih menu di bawah untuk mulai."
    )


# ── Kirim / edit pesan ────────────────────────────────────────────────────────

async def edit_or_send(query, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    """
    Edit pesan callback dengan teks baru. Jika pesan asal berupa foto/media
    (tidak bisa di-edit jadi teks), pesan dihapus lalu dikirim ulang.
    """
    msg = query.message
    if msg is not None and not (msg.photo or msg.document or msg.video):
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML,
                                          disable_web_page_preview=True)
            return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
    try:
        if msg is not None:
            await msg.delete()
    except Exception:
        pass
    chat_id = msg.chat_id if msg is not None else query.from_user.id
    await query.get_bot().send_message(chat_id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML,
                                       disable_web_page_preview=True)


async def replace_with_photo(query, photo, caption: str, reply_markup: InlineKeyboardMarkup | None = None):
    """Ganti pesan callback dengan foto + caption (pesan lama dihapus)."""
    msg = query.message
    try:
        if msg is not None:
            await msg.delete()
    except Exception:
        pass
    chat_id = msg.chat_id if msg is not None else query.from_user.id
    return await query.get_bot().send_photo(chat_id, photo=photo, caption=caption,
                                            reply_markup=reply_markup, parse_mode=ParseMode.HTML)


# ── Label status order ────────────────────────────────────────────────────────

STATUS_LABEL = {
    "pending": "⏳ Menunggu bayar",
    "verifying": "🔍 Diverifikasi admin",
    "paid": "✅ Lunas",
    "rejected": "❌ Ditolak",
    "expired": "⌛ Kedaluwarsa",
    "cancelled": "🚫 Dibatalkan",
}
