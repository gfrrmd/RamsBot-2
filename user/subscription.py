from ui import LINE, esc, fmt_dt, fmt_remaining, get_sub_state, header, kv, session_badge, uptime_str
from database import get_user_qris


def build_subscription_text(uid: int, full_name: str = None, username: str = None) -> str:
    """Kartu Status Akun (HTML)."""
    s = get_sub_state(uid)
    uname = f"@{esc(username)}" if username else "—"
    if s["state"] == "none":
        plan, exp, sisa = "—", "—", "—"
    else:
        plan = "Trial 🎟️" if s["plan"] == "trial" else "VIP 💎"
        exp = esc(fmt_dt(s["expired"]))
        if s["state"] == "active":
            sisa = fmt_remaining(s["remaining"])
        else:
            sisa = "⚠️ Expired" if s["state"] == "expired" else "🚫 Dicabut"
    return (
        f"{header('👤', 'Status Akun')}\n"
        f"{kv('Nama', esc(full_name), 10)}\n"
        f"{kv('Username', uname, 10)}\n"
        f"{kv('ID', '<code>' + str(uid) + '</code>', 10)}\n"
        f"{LINE}\n"
        f"{kv('Plan', plan, 10)}\n"
        f"{kv('Expired', exp, 10)}\n"
        f"{kv('Sisa', sisa, 10)}\n"
        f"{LINE}\n"
        f"{kv('Bot', session_badge(uid), 10)}\n"
        f"{kv('Uptime', uptime_str(uid), 10)}\n"
        f"{kv('QRIS', 'Tersimpan ✅' if get_user_qris(uid) else 'Belum ada', 10)}"
    )
