"""Panel admin: statistik, daftar VIP, cek user, pengumuman, auto backup."""
import asyncio
import re

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter

from admin import autobackup
from admin.vip import _do_revoke
from auth.states import admin_state
from client_manager import active_clients
from database import (
    count_vip_active,
    extend_subscription,
    get_all_user_ids,
    get_stats,
    get_user_profile,
    get_vip_page,
    resolve_user_id,
    set_setting,
    upsert_user,
)
from services.session_runner import ensure_client_running
from ui import edit_or_send, esc, fmt_date, fmt_dt, fmt_remaining, header, kv, rp, sub_badge, get_sub_state

PAGE = 8
_bg_tasks: set = set()


# ── Statistik ─────────────────────────────────────────────────────────────────

def build_stats_text() -> str:
    s = get_stats()
    online = sum(1 for c in active_clients.values() if c.is_connected())
    return (
        f"{header('📊', 'Statistik Bot')}\n"
        f"{kv('Total user', s['users'], 13)}\n"
        f"{kv('VIP aktif', s['vip_active'], 13)}\n"
        f"{kv('Trial aktif', s['trial_active'], 13)}\n"
        f"{kv('VIP ≤ 3 hari', s['vip_expiring'], 13)}\n"
        f"{kv('VIP expired', s['vip_expired'], 13)}\n"
        f"{kv('Session', str(s['sessions']) + ' tersimpan - ' + str(online) + ' online', 13)}\n"
        f"{kv('QRIS user', s['qris_saved'], 13)}\n"
        "\n"
        f"🧾 Order: {s['orders_pending']} pending - {s['orders_verifying']} verifikasi - {s['orders_paid']} lunas\n"
        f"💰 Hari ini: <b>{rp(s['revenue_today'])}</b>\n"
        f"💰 30 hari: <b>{rp(s['revenue_30d'])}</b>\n"
        f"💰 Total: <b>{rp(s['revenue_total'])}</b>\n"
        f"💾 Auto backup: {'ON ✅' if autobackup.is_enabled() else 'OFF ❌'}"
    )


def admin_home_text() -> str:
    s = get_stats()
    waiting = s["orders_pending"] + s["orders_verifying"]
    return (
        f"{header('🛠️', 'Panel Admin')}\n"
        f"Total user: {s['users']}\n"
        f"VIP aktif: {s['vip_active']}\n"
        f"Order menunggu: {waiting}\n\n"
        "Pilih menu di bawah:"
    ), waiting


# ── Kartu user ────────────────────────────────────────────────────────────────

def build_user_card(user_id: int):
    p = get_user_profile(user_id)
    if not p:
        return None, None
    sub = get_sub_state(user_id)
    exp = fmt_dt(sub["expired"]) if sub["expired"] else "—"
    client = active_clients.get(user_id)
    if client and client.is_connected():
        sess = "Online ✅"
    elif p["has_session"]:
        sess = "Tersimpan (offline)"
    else:
        sess = "Belum setup"
    uname = f"@{esc(p['username'])}" if p["username"] else "—"
    name_link = '<a href="tg://user?id=' + str(user_id) + '">' + esc(p["full_name"]) + "</a>"
    id_code = "<code>" + str(user_id) + "</code>"
    text = (
        f"{header('👤', 'Info User')}\n"
        f"{kv('Nama', name_link, 10)}\n"
        f"{kv('Username', uname, 10)}\n"
        f"{kv('ID', id_code, 10)}\n"
        f"{kv('Akun', sub_badge(user_id), 10)}\n"
        f"{kv('Expired', esc(exp), 10)}\n"
        f"{kv('Session', sess, 10)}\n"
        f"{kv('QRIS', 'Tersimpan ✅' if p['has_qris'] else '—', 10)}\n"
        f"{kv('Trial', 'Sudah dipakai' if p['trial_used'] else 'Belum', 10)}\n"
        f"{kv('Order lunas', str(p['paid_orders']) + ' - ' + rp(p['paid_total']), 10)}\n"
        f"{kv('Daftar', esc(fmt_date(p['created_at'])), 10)}"
    )
    kb = InlineKeyboardMarkup([
        [Btn("➕ 7 hari", callback_data=f"admin_u_add_{user_id}_7"), Btn("➕ 30 hari", callback_data=f"admin_u_add_{user_id}_30")],
        [Btn("🚫 Revoke VIP", callback_data=f"admin_u_rev_{user_id}")],
        [Btn("🔙 Panel Admin", callback_data="menu_admin")],
    ])
    return text, kb


# ── Pengumuman ────────────────────────────────────────────────────────────────

async def _do_announce(bot, admin_id: int, from_chat: int, message_id: int, progress):
    ids = get_all_user_ids()
    ok = blocked = failed = 0
    for i, uid in enumerate(ids, 1):
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=from_chat, message_id=message_id)
            ok += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=from_chat, message_id=message_id)
                ok += 1
            except Exception:
                failed += 1
        except Forbidden:
            blocked += 1
        except Exception:
            failed += 1
        if i % 25 == 0:
            try:
                await progress.edit_text(f"📢 Mengirim... {i}/{len(ids)}")
            except Exception:
                pass
        await asyncio.sleep(0.05)
    try:
        await progress.edit_text(
            f"✅ <b>Pengumuman selesai</b>\nTerkirim: {ok}\nDiblokir user: {blocked}\nGagal: {failed}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[Btn("🔙 Panel Admin", callback_data="menu_admin")]]))
    except Exception:
        pass


# ── Dispatcher callback ───────────────────────────────────────────────────────

async def handle_callback(query, context, data: str) -> bool:
    uid = query.from_user.id
    back = InlineKeyboardMarkup([[Btn("🔙 Panel Admin", callback_data="menu_admin")]])

    if data == "admin_stats":
        await edit_or_send(query, build_stats_text(), back)
        return True

    m = re.fullmatch(r"admin_viplist_(\d+)", data)
    if m:
        page = int(m.group(1))
        total = count_vip_active()
        rows_db = get_vip_page(PAGE, page * PAGE)
        lines = [header("👑", f"List VIP ({total} aktif)")]
        btns = []
        if not rows_db:
            lines.append("Belum ada VIP aktif.")
        for i, u in enumerate(rows_db, page * PAGE + 1):
            name = u["full_name"] or str(u["user_id"])
            uname = f" (@{esc(u['username'])})" if u["username"] else ""
            left = get_sub_state(u["user_id"])["remaining"]
            lines.append(f"<b>{i}.</b> {esc(name)}{uname}\n   <code>{u['user_id']}</code> - s/d {esc(fmt_date(u['expired_at']))} ({fmt_remaining(left) if left else '—'})")
            btns.append(Btn(f"{i}. {name[:18]}", callback_data=f"admin_u_{u['user_id']}"))
        kb = [btns[i:i + 2] for i in range(0, len(btns), 2)]
        nav = []
        if page > 0:
            nav.append(Btn("⬅️", callback_data=f"admin_viplist_{page - 1}"))
        if (page + 1) * PAGE < total:
            nav.append(Btn("➡️", callback_data=f"admin_viplist_{page + 1}"))
        if nav:
            kb.append(nav)
        kb.append([Btn("🔙 Panel Admin", callback_data="menu_admin")])
        lines.append("\n💡 Tap nama untuk kelola user.")
        await edit_or_send(query, "\n".join(lines), InlineKeyboardMarkup(kb))
        return True

    if data == "admin_finduser":
        admin_state[uid] = {"action": "finduser"}
        await edit_or_send(query, f"{header('🔎', 'Cek User')}\nKirim <b>user ID</b> atau <b>@username</b>.\n\nKetik /cancel untuk batal.",
                           InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="menu_admin")]]))
        return True

    m = re.fullmatch(r"admin_u_(\d+)", data)
    if m:
        text, kb = build_user_card(int(m.group(1)))
        if not text:
            await query.answer("User tidak ditemukan.", show_alert=True)
        else:
            await edit_or_send(query, text, kb)
        return True

    m = re.fullmatch(r"admin_u_add_(\d+)_(\d+)", data)
    if m:
        target, days = int(m.group(1)), int(m.group(2))
        upsert_user(target, None, None) if get_user_profile(target) is None else None
        expired = extend_subscription(target, days)
        sess = await ensure_client_running(target, context.bot)
        try:
            await context.bot.send_message(target, f"🎁 VIP kamu ditambah <b>{days} hari</b>.\nAktif hingga <b>{esc(fmt_dt(expired))}</b>.", parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await query.answer(f"+{days} hari. Session: {sess.split(':')[0]}", show_alert=True)
        text, kb = build_user_card(target)
        await edit_or_send(query, text, kb)
        return True

    m = re.fullmatch(r"admin_u_rev_(\d+)", data)
    if m:
        target = int(m.group(1))
        ok, msg = await _do_revoke(str(target), context)
        await query.answer(("✅ " if ok else "⚠️ ") + msg.split("\n")[0][:180], show_alert=True)
        text, kb = build_user_card(target)
        if text:
            await edit_or_send(query, text, kb)
        return True

    if data == "admin_announce":
        admin_state[uid] = {"action": "announce"}
        await edit_or_send(
            query,
            f"{header('📢', 'Pengumuman')}\nKirim pesan yang ingin disebar ke <b>{len(get_all_user_ids())} user</b> bot "
            "(teks, foto, video, dll — format asli dipertahankan).\n\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="menu_admin")]]))
        return True

    if data == "admin_ann_go":
        st = admin_state.pop(uid, None)
        if not st or st.get("action") != "announce_confirm":
            await query.answer("Draft pengumuman sudah tidak ada.", show_alert=True)
            return True
        progress = await context.bot.send_message(uid, "📢 Mengirim...")
        task = asyncio.create_task(_do_announce(context.bot, uid, st["chat_id"], st["message_id"], progress))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
        await edit_or_send(query, "⏳ Pengumuman sedang dikirim di latar belakang.", back)
        return True

    # ── auto backup ──
    if data == "admin_autobackup":
        await edit_or_send(query, autobackup.build_autobackup_text(), autobackup.autobackup_keyboard())
        return True
    if data == "admin_ab_toggle":
        set_setting("ab_enabled", "0" if autobackup.is_enabled() else "1")
        await edit_or_send(query, autobackup.build_autobackup_text(), autobackup.autobackup_keyboard())
        return True
    m = re.fullmatch(r"admin_ab_int_(\d+)", data)
    if m:
        set_setting("ab_interval_h", int(m.group(1)))
        await edit_or_send(query, autobackup.build_autobackup_text(), autobackup.autobackup_keyboard())
        return True
    if data == "admin_ab_channel":
        admin_state[uid] = {"action": "ab_channel"}
        await edit_or_send(
            query,
            f"{header('📡', 'Channel Backup')}\nKirim <b>ID channel</b> tujuan (contoh <code>-1001234567890</code>). "
            "Bot harus jadi <b>admin</b> di channel itu.\nKetik <code>off</code> untuk memakai PM admin saja.\n\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="admin_autobackup")]]))
        return True
    if data == "admin_ab_now":
        await query.answer("⏳ Membuat backup...")
        ok, info = await autobackup.run_backup(context.bot, "now")
        await query.answer(("✅ Terkirim: " if ok else "❌ Gagal: ") + info[:150], show_alert=True)
        await edit_or_send(query, autobackup.build_autobackup_text(), autobackup.autobackup_keyboard())
        return True

    return False


# ── State teks dari admin ─────────────────────────────────────────────────────

async def handle_state_message(update, context, state: dict) -> bool:
    action = state.get("action")
    msg = update.effective_message
    uid = update.effective_user.id
    text = (msg.text or "").strip()

    if action == "finduser":
        if not text:
            await msg.reply_text("❌ Kirim user ID atau @username, atau /cancel.")
            return True
        target = resolve_user_id(text)
        card, kb = build_user_card(target) if target else (None, None)
        if not card:
            await msg.reply_text("❌ User tidak ditemukan di database. Coba user ID (angka), atau /cancel.")
            return True
        admin_state.pop(uid, None)
        await msg.reply_text(card, parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
        return True

    if action == "announce":
        admin_state[uid] = {"action": "announce_confirm", "chat_id": msg.chat_id, "message_id": msg.message_id}
        await msg.reply_text(
            f"Kirim pesan ini ke <b>{len(get_all_user_ids())} user</b>?", parse_mode=ParseMode.HTML, reply_to_message_id=msg.message_id,
            reply_markup=InlineKeyboardMarkup([[Btn("✅ Kirim", callback_data="admin_ann_go"), Btn("❌ Batal", callback_data="menu_admin")]]))
        return True

    if action == "ab_channel":
        if text.lower() in ("off", "0"):
            set_setting("ab_channel", "0")
            admin_state.pop(uid, None)
            await msg.reply_text("✅ Backup hanya dikirim ke PM admin.", reply_markup=InlineKeyboardMarkup([[Btn("💾 Auto Backup", callback_data="admin_autobackup")]]))
            return True
        if not re.fullmatch(r"-?\d{5,}", text):
            await msg.reply_text("❌ ID tidak valid. Contoh: <code>-1001234567890</code>, atau <code>off</code>.", parse_mode=ParseMode.HTML)
            return True
        try:
            await context.bot.send_message(int(text), "✅ Channel ini terhubung sebagai tujuan Auto Backup RamsBot.")
        except Exception as e:
            await msg.reply_text(f"❌ Bot tidak bisa mengirim ke channel itu: {e}\nPastikan bot sudah jadi admin.")
            return True
        set_setting("ab_channel", text)
        admin_state.pop(uid, None)
        await msg.reply_text("✅ Channel backup disimpan.", reply_markup=InlineKeyboardMarkup([[Btn("💾 Auto Backup", callback_data="admin_autobackup")]]))
        return True

    return False
