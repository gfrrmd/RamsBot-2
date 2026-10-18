from database import blacklist_add, blacklist_list, blacklist_remove
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
