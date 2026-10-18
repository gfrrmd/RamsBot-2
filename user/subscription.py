from ui import esc, fmt_dt, fmt_remaining, get_sub_state, header, session_badge, uptime_str


def build_subscription_text(uid: int, full_name: str = None, username: str = None) -> str:
    """Kartu Status Akun (HTML) dengan label seperti RamsBot asli."""
    s = get_sub_state(uid)
    uname = "@" + esc(username) if username else "—"
    if s["state"] == "none":
        plan, exp, sisa = "—", "—", "—"
    else:
        plan = "Trial" if s["plan"] == "trial" else "VIP 💎"
        exp = esc(fmt_dt(s["expired"]))
        if s["state"] == "active":
            sisa = fmt_remaining(s["remaining"])
        else:
            sisa = "Expired ⚠️" if s["state"] == "expired" else "Dicabut 🚫"
    return (
        header("👤", "Status Akun") + "\n"
        f"Pengguna: {esc(full_name)}\n"
        f"Username: {uname}\n"
        f"ID: <code>{uid}</code>\n"
        f"Status Bot: {session_badge(uid)}\n"
        f"Plan: {plan}\n"
        f"Expired: {exp}\n"
        f"Sisa: {sisa}\n"
        f"Uptime Bot: {uptime_str(uid)}"
    )
