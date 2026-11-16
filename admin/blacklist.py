from database import blacklist_add, blacklist_list, blacklist_remove, restricted_account_list
from ui import esc, header


def build_blacklist_text() -> str:
    rows = blacklist_list()
    if not rows:
        return f"{header('🔒', 'Blacklist Channel')}\nDaftar kosong."
    lines = [header("🔒", "Blacklist Channel")]
    for i, r in enumerate(rows, 1):
        note = f" — {esc(r['note'])}" if r.get("note") else ""
        date = (r.get("added_at") or "")[:10]
        lines.append(f"{i}. <code>{esc(r['identifier'])}</code>{note} <i>(ditambah {date})</i>")
    return "\n".join(lines)


def build_restricted_account_text() -> str:
    rows = restricted_account_list()
    if not rows:
        return f"{header('👤', 'Restricted Account')}\nDaftar kosong."
    lines = [header("👤", "Restricted Account")]
    for i, r in enumerate(rows, 1):
        ident = []
        if r.get("username"):
            ident.append(f"@{esc(r['username'])}")
        if r.get("user_id"):
            ident.append(f"<code>{r['user_id']}</code>")
        note = f" — {esc(r['note'])}" if r.get("note") else ""
        date = (r.get("added_at") or "")[:10]
        lines.append(f"{i}. {' · '.join(ident)}{note} <i>(ditambah {date})</i>")
    return "\n".join(lines)
