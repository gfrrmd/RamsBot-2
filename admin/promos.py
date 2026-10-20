"""Panel admin: kode promo (diskon 1-100%) dan voucher klaim VIP."""
import re
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.constants import ParseMode

from auth.states import admin_state
from database import (
    add_promo,
    add_voucher,
    add_vouchers_bulk,
    count_promos,
    count_vouchers,
    delete_promo,
    delete_voucher,
    get_promo,
    get_promos,
    get_voucher,
    get_voucher_claims,
    get_vouchers,
    set_promo_active,
    set_voucher_active,
)
from keyboards import nav_row, page_info
from ui import edit_or_send, esc, fmt_dt, header
from utils.codes import generate_code, normalize_code, parse_percent

PAGE = 8
HTML = ParseMode.HTML
MAX_BULK = 50


# ── Util ──────────────────────────────────────────────────────────────────────

def _expires_iso(days: int) -> str | None:
    return (datetime.now() + timedelta(days=days)).isoformat() if days else None


def _exp_text(exp: str | None) -> str:
    return esc(fmt_dt(exp)) if exp else "Tanpa batas"


def _expired(exp: str | None) -> bool:
    try:
        return bool(exp) and datetime.fromisoformat(exp) <= datetime.now()
    except Exception:
        return False


def _mark(active: bool, exp: str | None) -> str:
    if not active:
        return "⏸️"
    return "⌛" if _expired(exp) else "✅"


def _quota(n: int) -> str:
    return str(n) if n else "∞"


def _parts(text: str) -> list[str]:
    return [x.strip() for x in text.split("|")]


def _opt_int(parts: list[str], idx: int, default: int, lo: int, hi: int) -> int | None:
    """Angka opsional di posisi idx. Kosong/tidak ada -> default. Tidak valid -> None."""
    if len(parts) <= idx or parts[idx] == "":
        return default
    if not parts[idx].isdigit():
        return None
    n = int(parts[idx])
    return n if lo <= n <= hi else None


# ── Layar promo ───────────────────────────────────────────────────────────────

async def _show_promos(query, page: int = 0):
    total = count_promos()
    page = max(0, min(page, max(0, (total - 1) // PAGE)))
    lines = [header("🏷️", "Kode Promo").rstrip(), f"Total: {total} kode"]
    rows = []
    if not total:
        lines.append("Belum ada kode promo. Tekan Buat Promo untuk membuat.")
    for p in get_promos(PAGE, page * PAGE):
        label = f"{_mark(p['is_active'], p['expires_at'])} {p['code']} - {p['percent']}% - {p['used']}/{_quota(p['max_uses'])}"
        rows.append([Btn(label, callback_data=f"admin_promo_{p['id']}")])
    lines.append("✅ aktif, ⏸️ nonaktif, ⌛ kedaluwarsa. Angka = terpakai/kuota.")
    nav = nav_row("admin_promos_", page, total, PAGE)
    if nav:
        rows.append(nav)
        lines.append(page_info(page, total, PAGE))
    rows.append([Btn("➕ Buat Promo", callback_data="admin_promo_add")])
    rows.append([Btn("🔙 Panel Admin", callback_data="menu_admin")])
    await edit_or_send(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _show_promo(query, promo_id: int):
    p = get_promo(promo_id)
    if not p:
        await _show_promos(query)
        return
    status = "Aktif ✅" if p["is_active"] else "Nonaktif ⏸️"
    if p["is_active"] and _expired(p["expires_at"]):
        status = "Kedaluwarsa ⌛"
    text = (
        header("🏷️", p["code"])
        + f"Diskon: {p['percent']}%\n"
        f"Dipakai: {p['used']} dari {_quota(p['max_uses'])}\n"
        f"Berlaku s/d: {_exp_text(p['expires_at'])}\n"
        f"Status: {status}\n"
        "Tiap user hanya bisa memakai kode ini 1 kali."
    )
    kb = InlineKeyboardMarkup([
        [Btn("⏸️ Nonaktifkan" if p["is_active"] else "▶️ Aktifkan", callback_data=f"admin_promo_tog_{promo_id}"),
         Btn("🗑️ Hapus", callback_data=f"admin_promo_del_{promo_id}")],
        [Btn("🔙 Daftar Promo", callback_data="admin_promos")],
    ])
    await edit_or_send(query, text, kb)


# ── Layar voucher ─────────────────────────────────────────────────────────────

async def _show_vouchers(query, page: int = 0):
    total = count_vouchers()
    page = max(0, min(page, max(0, (total - 1) // PAGE)))
    lines = [header("🎟️", "Voucher VIP").rstrip(), f"Total: {total} voucher"]
    rows = []
    if not total:
        lines.append("Belum ada voucher. Tekan Buat Voucher untuk membuat.")
    for v in get_vouchers(PAGE, page * PAGE):
        label = f"{_mark(v['is_active'], v['expires_at'])} {v['code']} - {v['days']}h - {v['claimed']}/{_quota(v['max_claims'])}"
        rows.append([Btn(label, callback_data=f"admin_vch_{v['id']}")])
    lines.append("✅ aktif, ⏸️ nonaktif, ⌛ kedaluwarsa. Angka = diklaim/kuota.")
    nav = nav_row("admin_vchs_", page, total, PAGE)
    if nav:
        rows.append(nav)
        lines.append(page_info(page, total, PAGE))
    rows.append([Btn("➕ Buat Voucher", callback_data="admin_vch_add"), Btn("📦 Buat Banyak", callback_data="admin_vch_bulk")])
    rows.append([Btn("🔙 Panel Admin", callback_data="menu_admin")])
    await edit_or_send(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _show_voucher(query, voucher_id: int):
    v = get_voucher(voucher_id)
    if not v:
        await _show_vouchers(query)
        return
    status = "Aktif ✅" if v["is_active"] else "Nonaktif ⏸️"
    if v["is_active"] and _expired(v["expires_at"]):
        status = "Kedaluwarsa ⌛"
    lines = [
        header("🎟️", v["code"]).rstrip(),
        f"Hadiah: {v['days']} hari VIP",
        f"Diklaim: {v['claimed']} dari {_quota(v['max_claims'])}",
        f"Berlaku s/d: {_exp_text(v['expires_at'])}",
        f"Status: {status}",
    ]
    claims = get_voucher_claims(voucher_id, 5)
    if claims:
        lines.append("Pengklaim terbaru:")
        for c in claims:
            uname = f" (@{esc(c['username'])})" if c["username"] else ""
            lines.append(f"• {esc(c['full_name'] or c['user_id'])}{uname} <code>{c['user_id']}</code>")
    kb = InlineKeyboardMarkup([
        [Btn("⏸️ Nonaktifkan" if v["is_active"] else "▶️ Aktifkan", callback_data=f"admin_vch_tog_{voucher_id}"),
         Btn("🗑️ Hapus", callback_data=f"admin_vch_del_{voucher_id}")],
        [Btn("🔙 Daftar Voucher", callback_data="admin_vchs")],
    ])
    await edit_or_send(query, "\n".join(lines), kb)


# ── Dispatcher callback ───────────────────────────────────────────────────────

async def handle_callback(query, context, data: str) -> bool:
    """Return True jika callback ini milik modul promo/voucher."""
    uid = query.from_user.id

    # ── promo ──
    m = re.fullmatch(r"admin_promos(?:_(\d+))?", data)
    if m:
        await _show_promos(query, int(m.group(1) or 0))
        return True

    if data == "admin_promo_add":
        admin_state[uid] = {"action": "promo_add"}
        await edit_or_send(
            query,
            header("➕", "Buat Kode Promo")
            + "Kirim dengan format:\n<code>Kode | Persen | Kuota | Berlaku (hari)</code>\n"
            "Kuota dan masa berlaku boleh dikosongkan (0 = tanpa batas). Persen 1 sampai 100.\n"
            "Contoh:\n<code>HEMAT20 | 20 | 50 | 7</code>\n<code>FULL100 | 100 | 1</code>\n<code>acak | 15</code>\n"
            "Tulis <code>acak</code> pada kode untuk dibuatkan otomatis.\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="admin_promos")]]),
        )
        return True

    m = re.fullmatch(r"admin_promo_(tog|del|delok)_(\d+)", data)
    if m:
        action, pid = m.group(1), int(m.group(2))
        if action == "tog":
            p = get_promo(pid)
            if p:
                set_promo_active(pid, not p["is_active"])
            await _show_promo(query, pid)
        elif action == "del":
            await edit_or_send(
                query,
                header("🗑️", "Hapus Kode Promo?") + "Kode dihapus permanen. Riwayat order yang memakainya tetap aman.",
                InlineKeyboardMarkup([[Btn("✅ Ya, hapus", callback_data=f"admin_promo_delok_{pid}"),
                                       Btn("❌ Batal", callback_data=f"admin_promo_{pid}")]]),
            )
        else:
            delete_promo(pid)
            await _show_promos(query)
        return True

    m = re.fullmatch(r"admin_promo_(\d+)", data)
    if m:
        await _show_promo(query, int(m.group(1)))
        return True

    # ── voucher ──
    m = re.fullmatch(r"admin_vchs(?:_(\d+))?", data)
    if m:
        await _show_vouchers(query, int(m.group(1) or 0))
        return True

    if data == "admin_vch_add":
        admin_state[uid] = {"action": "vch_add"}
        await edit_or_send(
            query,
            header("➕", "Buat Voucher")
            + "Kirim dengan format:\n<code>Kode | Hari VIP | Kuota | Berlaku (hari)</code>\n"
            "Kuota default 1 (0 = tanpa batas). Masa berlaku boleh dikosongkan (tanpa batas).\n"
            "Contoh:\n<code>GRATIS7 | 7 | 10 | 14</code>\n<code>acak | 30</code>\n"
            "Tulis <code>acak</code> pada kode untuk dibuatkan otomatis.\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="admin_vchs")]]),
        )
        return True

    if data == "admin_vch_bulk":
        admin_state[uid] = {"action": "vch_bulk"}
        await edit_or_send(
            query,
            header("📦", "Buat Voucher Banyak")
            + f"Buat banyak voucher sekali pakai dengan kode acak (maks {MAX_BULK}).\n"
            "Format:\n<code>Hari VIP | Jumlah | Berlaku (hari)</code>\n"
            "Masa berlaku boleh dikosongkan.\nContoh:\n<code>30 | 20</code>\n<code>7 | 10 | 14</code>\n"
            "Ketik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="admin_vchs")]]),
        )
        return True

    m = re.fullmatch(r"admin_vch_(tog|del|delok)_(\d+)", data)
    if m:
        action, vid = m.group(1), int(m.group(2))
        if action == "tog":
            v = get_voucher(vid)
            if v:
                set_voucher_active(vid, not v["is_active"])
            await _show_voucher(query, vid)
        elif action == "del":
            await edit_or_send(
                query,
                header("🗑️", "Hapus Voucher?") + "Voucher dan riwayat klaimnya dihapus permanen. "
                "VIP yang sudah terlanjur diklaim user tidak berubah.",
                InlineKeyboardMarkup([[Btn("✅ Ya, hapus", callback_data=f"admin_vch_delok_{vid}"),
                                       Btn("❌ Batal", callback_data=f"admin_vch_{vid}")]]),
            )
        else:
            delete_voucher(vid)
            await _show_vouchers(query)
        return True

    m = re.fullmatch(r"admin_vch_(\d+)", data)
    if m:
        await _show_voucher(query, int(m.group(1)))
        return True

    return False


# ── Input teks dari admin (state) ─────────────────────────────────────────────

async def handle_state_message(update, context, state: dict) -> bool:
    """Return True jika pesan ini ditangani (state milik modul promo/voucher)."""
    action = state.get("action")
    if action not in ("promo_add", "vch_add", "vch_bulk"):
        return False
    msg = update.effective_message
    uid = update.effective_user.id
    parts = _parts((msg.text or "").strip())
    back_promo = InlineKeyboardMarkup([[Btn("🏷️ Daftar Promo", callback_data="admin_promos")]])
    back_vch = InlineKeyboardMarkup([[Btn("🎟️ Daftar Voucher", callback_data="admin_vchs")]])

    if action == "promo_add":
        code = percent = quota = days = None
        if 2 <= len(parts) <= 4:
            code = generate_code(8) if parts[0].lower() in ("acak", "random") else normalize_code(parts[0])
            percent = parse_percent(parts[1])
            quota = _opt_int(parts, 2, 0, 0, 1_000_000)
            days = _opt_int(parts, 3, 0, 0, 3650)
        if code is None or percent is None or quota is None or days is None:
            await msg.reply_text(
                "❌ Format salah. Gunakan:\n<code>Kode | Persen | Kuota | Berlaku (hari)</code>\n"
                "Kode 3 sampai 20 karakter (huruf, angka, _ atau -), persen 1 sampai 100.\n"
                "Contoh: <code>HEMAT20 | 20 | 50 | 7</code>\nAtau /cancel.",
                parse_mode=HTML)
            return True
        pid = add_promo(code, percent, quota, _expires_iso(days))
        if pid is None:
            await msg.reply_text(f"⚠️ Kode <code>{code}</code> sudah ada. Kirim kode lain atau /cancel.", parse_mode=HTML)
            return True
        admin_state.pop(uid, None)
        await msg.reply_text(
            header("✅", "Kode Promo Dibuat")
            + f"Kode: <code>{code}</code>\nDiskon: {percent}%\nKuota: {_quota(quota)}\n"
            f"Berlaku s/d: {_exp_text(_expires_iso(days))}",
            parse_mode=HTML, reply_markup=back_promo)
        return True

    if action == "vch_add":
        code = days = quota = valid = None
        if 2 <= len(parts) <= 4:
            code = generate_code(10) if parts[0].lower() in ("acak", "random") else normalize_code(parts[0])
            days = _opt_int(parts, 1, -1, 1, 3650)
            quota = _opt_int(parts, 2, 1, 0, 1_000_000)
            valid = _opt_int(parts, 3, 0, 0, 3650)
        if code is None or days in (None, -1) or quota is None or valid is None:
            await msg.reply_text(
                "❌ Format salah. Gunakan:\n<code>Kode | Hari VIP | Kuota | Berlaku (hari)</code>\n"
                "Hari VIP 1 sampai 3650. Contoh: <code>GRATIS7 | 7 | 10 | 14</code>\nAtau /cancel.",
                parse_mode=HTML)
            return True
        vid = add_voucher(code, days, quota, _expires_iso(valid))
        if vid is None:
            await msg.reply_text(f"⚠️ Kode <code>{code}</code> sudah ada. Kirim kode lain atau /cancel.", parse_mode=HTML)
            return True
        admin_state.pop(uid, None)
        await msg.reply_text(
            header("✅", "Voucher Dibuat")
            + f"Kode: <code>{code}</code>\nHadiah: {days} hari VIP\nKuota: {_quota(quota)}\n"
            f"Berlaku s/d: {_exp_text(_expires_iso(valid))}",
            parse_mode=HTML, reply_markup=back_vch)
        return True

    # vch_bulk
    days = count = valid = None
    if 2 <= len(parts) <= 3:
        days = _opt_int(parts, 0, -1, 1, 3650)
        count = _opt_int(parts, 1, -1, 1, MAX_BULK)
        valid = _opt_int(parts, 2, 0, 0, 3650)
    if days in (None, -1) or count in (None, -1) or valid is None:
        await msg.reply_text(
            f"❌ Format salah. Gunakan:\n<code>Hari VIP | Jumlah | Berlaku (hari)</code>\n"
            f"Jumlah 1 sampai {MAX_BULK}. Contoh: <code>30 | 20</code>\nAtau /cancel.",
            parse_mode=HTML)
        return True
    codes = add_vouchers_bulk(days, count, _expires_iso(valid))
    admin_state.pop(uid, None)
    await msg.reply_text(
        header("✅", f"{len(codes)} Voucher Dibuat")
        + f"Hadiah: {days} hari VIP per voucher, sekali pakai.\n"
        f"Berlaku s/d: {_exp_text(_expires_iso(valid))}\n"
        f"<pre>{chr(10).join(codes)}</pre>",
        parse_mode=HTML, reply_markup=back_vch)
    return True
