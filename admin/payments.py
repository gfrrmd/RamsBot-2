"""Panel admin untuk pembayaran: QRIS tujuan, paket, kode unik, dan verifikasi order."""
import asyncio
import re

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.constants import ParseMode

from auth.states import admin_state
from config import ADMIN_ID
from database import (
    add_plan,
    approve_order,
    count_orders,
    delete_plan,
    get_order,
    get_plan,
    get_plans,
    get_setting,
    get_user_profile,
    list_orders,
    set_plan_active,
    set_setting,
    update_order_status,
    update_plan,
)
from keyboards import main_keyboard, order_admin_keyboard
from services.session_runner import ensure_client_running
from ui import STATUS_LABEL, edit_or_send, esc, fmt_dt, header, kv, rp, sub_badge, replace_with_photo
from utils.qris import QRISError, convert_qris, parse_amount, render_qr_png, summarize_qris

PAGE = 8
OPEN_STATUSES = ("pending", "verifying", "expired")


# ── Notifikasi bukti bayar masuk ──────────────────────────────────────────────

def _user_line(user_id: int, name: str | None, username: str | None) -> str:
    uname = f" (@{esc(username)})" if username else ""
    return f'<a href="tg://user?id={user_id}">{esc(name or user_id)}</a>{uname} - <code>{user_id}</code>'


def _order_admin_text(order: dict) -> str:
    prof = get_user_profile(order["user_id"]) or {}
    lines = [
        header("🧾", f"Order #{order['id']}"),
        kv("User", _user_line(order["user_id"], prof.get("full_name"), prof.get("username")), 9),
        kv("Akun", sub_badge(order["user_id"]), 9),
        kv("Paket", f"{esc(order['plan_name'])} ({order['days']} hari)", 9),
        kv("Harga", rp(order["base_price"]), 9),
        kv("Kode unik", f"+{rp(order['unique_code'])}" if order["unique_code"] else "—", 9),
        kv("Total", f"<b>{rp(order['total'])}</b>", 9),
        kv("Status", STATUS_LABEL.get(order["status"], order["status"]), 9),
        kv("Dibuat", esc(fmt_dt(order["created_at"])), 9),
    ]
    if order.get("paid_at"):
        lines.append(kv("Lunas", esc(fmt_dt(order["paid_at"])), 9))
    return "\n".join(lines)


async def notify_admin_new_proof(bot, order: dict, user) -> None:
    caption = (
        f"💰 <b>Pembayaran masuk — cek mutasi</b>\n\n{_order_admin_text(order)}\n\n"
        f"Pastikan dana <b>{rp(order['total'])}</b> sudah masuk, lalu tekan Approve."
    )
    kind, _, file_id = (order.get("proof_file_id") or "").partition(":")
    kb = order_admin_keyboard(order["id"])
    try:
        if kind == "document":
            await bot.send_document(ADMIN_ID, file_id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await bot.send_photo(ADMIN_ID, file_id, caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        print(f"[payment] gagal kirim notifikasi admin: {e}")
        try:
            await bot.send_message(ADMIN_ID, caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            pass


# ── Approve / tolak ───────────────────────────────────────────────────────────

async def approve_and_notify(bot, order_id: int, admin_id: int) -> tuple[bool, str]:
    order = approve_order(order_id, admin_id)
    if not order:
        return False, "Order sudah diproses sebelumnya (atau tidak ditemukan)."
    uid = order["user_id"]
    sess = await ensure_client_running(uid, bot)
    if sess in ("started", "already"):
        extra = "🔌 Session kamu <b>otomatis aktif kembali</b> — fitur siap dipakai."
    elif sess == "no_session":
        extra = "✨ Lanjutkan dengan menekan <b>Setup Bot</b> untuk menghubungkan akunmu."
    else:
        extra = "⚠️ Session lama tidak bisa dijalankan. Silakan <b>Setup Bot</b> ulang."
    try:
        await bot.send_message(
            uid,
            f"{header('✅', 'Pembayaran Dikonfirmasi')}\n"
            f"{kv('Paket', esc(order['plan_name']), 9)}\n"
            f"{kv('Total', rp(order['total']), 9)}\n"
            f"{kv('VIP s/d', '<b>' + esc(fmt_dt(order['new_expired'])) + '</b>', 9)}\n"
            f"\n{extra}\n\nTerima kasih! 🙏",
            parse_mode=ParseMode.HTML, reply_markup=main_keyboard(uid),
        )
        notified = ""
    except Exception:
        notified = " (notifikasi ke user gagal dikirim)"
    return True, f"VIP user {uid} aktif sampai {fmt_dt(order['new_expired'])}{notified}"


async def reject_and_notify(bot, order_id: int, admin_id: int) -> tuple[bool, str]:
    order = get_order(order_id)
    if not order or not update_order_status(order_id, "rejected", ("pending", "verifying"), admin_id):
        return False, "Order sudah diproses sebelumnya (atau tidak ditemukan)."
    from config import ADMIN_CONTACT
    try:
        await bot.send_message(
            order["user_id"],
            f"{header('❌', 'Pembayaran Ditolak')}\nPesanan <b>#{order_id}</b> tidak dapat diverifikasi "
            f"(bukti tidak valid / dana belum masuk).\nJika kamu merasa ini keliru, hubungi admin {esc(ADMIN_CONTACT)} "
            "dengan bukti transfer.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[Btn("💎 Coba Lagi", callback_data="pay_menu")]]),
        )
    except Exception:
        pass
    return True, f"Order #{order_id} ditolak."


async def _append_status(query, line: str, back_cb: str = "admin_pay") -> None:
    """Tambahkan status di pesan order (caption foto / teks) & hapus tombol aksi."""
    m = query.message
    kb = InlineKeyboardMarkup([[Btn("🔙 Pembayaran", callback_data=back_cb)]])
    try:
        if m.photo or m.document:
            await query.edit_message_caption(caption=(m.caption_html or "") + f"\n\n{line}",
                                             parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await query.edit_message_text((m.text_html or "") + f"\n\n{line}", parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        pass


# ── Layar admin ───────────────────────────────────────────────────────────────

def _expire_minutes() -> int:
    try:
        return max(5, int(get_setting("pay_expire_min", "60")))
    except ValueError:
        return 60


def build_pay_admin_text() -> str:
    static = get_setting("pay_qris")
    plans = get_plans()
    active = [p for p in plans if p["is_active"]]
    if static:
        info = summarize_qris(static)
        qris_line = f"✅ {esc(info['merchant_name'])}"
    else:
        qris_line = "❌ Belum diatur"
    ready = bool(static) and bool(active)
    uniq_on = get_setting("pay_unique", "1") == "1"
    waiting = count_orders(("pending", "verifying"))
    paket = str(len(active)) + " dari " + str(len(plans))
    return (
        f"{header('💳', 'Pengaturan Pembayaran')}\n"
        f"{kv('QRIS bayar', qris_line, 11)}\n"
        f"{kv('Paket aktif', paket, 11)}\n"
        f"{kv('Kode unik', 'ON ✅' if uniq_on else 'OFF ❌', 11)}\n"
        f"{kv('Batas bayar', str(_expire_minutes()) + ' menit', 11)}\n"
        f"{kv('Menunggu', str(waiting) + ' order', 11)}\n"
        "\n"
        f"Status toko: {'🟢 Siap menerima pesanan' if ready else '🔴 Belum siap (atur QRIS & minimal 1 paket aktif)'}\n\n"
        "ℹ️ Pembeli membayar ke QRIS dinamis (nominal otomatis). Verifikasi dilakukan manual: "
        "cek mutasi, lalu tekan <b>Approve</b> pada notifikasi bukti bayar."
    )


def pay_admin_keyboard() -> InlineKeyboardMarkup:
    uniq = get_setting("pay_unique", "1") == "1"
    pending = count_orders(("pending", "verifying"))
    return InlineKeyboardMarkup([
        [Btn("🧾 Set QRIS Bayar", callback_data="admin_pay_setqris"), Btn("👁️ Lihat QRIS", callback_data="admin_pay_viewqris")],
        [Btn("📦 Kelola Paket", callback_data="admin_plans")],
        [Btn(f"🔢 Kode Unik: {'ON ✅' if uniq else 'OFF ❌'}", callback_data="admin_pay_uniq"), Btn("⏱️ Batas Waktu", callback_data="admin_pay_exp")],
        [Btn(f"🕓 Order Pending ({pending})", callback_data="admin_orders_pending"), Btn("📜 Riwayat", callback_data="admin_orders_hist_0")],
        [Btn("🔙 Panel Admin", callback_data="menu_admin")],
    ])


async def show_pay_admin(query):
    await edit_or_send(query, build_pay_admin_text(), pay_admin_keyboard())


async def _show_plans(query):
    plans = get_plans()
    lines = [header("📦", "Kelola Paket VIP")]
    rows = []
    if not plans:
        lines.append("Belum ada paket. Tekan <b>Tambah Paket</b> untuk membuat.")
    for p in plans:
        mark = "✅" if p["is_active"] else "⏸️"
        rows.append([Btn(f"{mark} {p['name']} - {p['days']}h - {rp(p['price'])}", callback_data=f"admin_plan_{p['id']}")])
    lines.append("\n✅ = tampil di menu beli - ⏸️ = disembunyikan")
    rows.append([Btn("➕ Tambah Paket", callback_data="admin_plan_add")])
    rows.append([Btn("🔙 Pembayaran", callback_data="admin_pay")])
    await edit_or_send(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _show_plan(query, plan_id: int):
    p = get_plan(plan_id)
    if not p:
        await _show_plans(query)
        return
    durasi = str(p["days"]) + " hari"
    status = "Aktif ✅" if p["is_active"] else "Disembunyikan ⏸️"
    text = (
        header("📦", p["name"]) + "\n"
        + kv("Durasi", durasi, 9) + "\n"
        + kv("Harga", rp(p["price"]), 9) + "\n"
        + kv("Status", status, 9)
    )
    kb = InlineKeyboardMarkup([
        [Btn("✏️ Edit", callback_data=f"admin_plan_edit_{plan_id}"),
         Btn("⏸️ Sembunyikan" if p["is_active"] else "▶️ Aktifkan", callback_data=f"admin_plan_tog_{plan_id}")],
        [Btn("🗑️ Hapus", callback_data=f"admin_plan_del_{plan_id}")],
        [Btn("🔙 Daftar Paket", callback_data="admin_plans")],
    ])
    await edit_or_send(query, text, kb)


async def _show_orders_list(query, statuses, title: str, page: int, back_cb: str, page_cb_prefix: str | None):
    total = count_orders(statuses)
    orders = list_orders(statuses, PAGE, page * PAGE)
    lines = [header("🧾", title)]
    rows = []
    if not orders:
        lines.append("Tidak ada order.")
    for o in orders:
        label = f"#{o['id']} - {rp(o['total'])} - {STATUS_LABEL.get(o['status'], o['status']).split(' ', 1)[0]}"
        rows.append([Btn(label, callback_data=f"admin_ord_view_{o['id']}")])
    if page_cb_prefix:
        nav = []
        if page > 0:
            nav.append(Btn("⬅️", callback_data=f"{page_cb_prefix}{page - 1}"))
        if (page + 1) * PAGE < total:
            nav.append(Btn("➡️", callback_data=f"{page_cb_prefix}{page + 1}"))
        if nav:
            rows.append(nav)
        lines.append(f"\nHalaman {page + 1} - total {total} order")
    rows.append([Btn("🔙 Pembayaran", callback_data=back_cb)])
    await edit_or_send(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def _show_order(query, context, order_id: int):
    order = get_order(order_id)
    if not order:
        await show_pay_admin(query)
        return
    text = _order_admin_text(order)
    rows = []
    if order["status"] in OPEN_STATUSES:
        rows.append([Btn("✅ Approve", callback_data=f"admin_ord_ok_{order_id}"), Btn("❌ Tolak", callback_data=f"admin_ord_no_{order_id}")])
    rows.append([Btn("🔙 Order Pending", callback_data="admin_orders_pending"), Btn("💳 Pembayaran", callback_data="admin_pay")])
    kb = InlineKeyboardMarkup(rows)
    kind, _, file_id = (order.get("proof_file_id") or "").partition(":")
    if file_id and kind == "photo":
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_photo(query.from_user.id, file_id, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return
    if file_id and kind == "document":
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_document(query.from_user.id, file_id, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return
    await edit_or_send(query, text + "\n\n<i>Belum ada bukti bayar.</i>", kb)


# ── Dispatcher callback ───────────────────────────────────────────────────────

async def handle_callback(query, context, data: str) -> bool:
    """Return True jika callback ini milik modul pembayaran."""
    uid = query.from_user.id

    if data == "admin_pay":
        await show_pay_admin(query)
        return True

    if data == "admin_pay_setqris":
        admin_state[uid] = {"action": "pay_qris"}
        await edit_or_send(
            query,
            f"{header('🧾', 'Set QRIS Pembayaran')}\nKirim <b>gambar QRIS statis</b> milikmu (tempat menerima uang pembayaran VIP), "
            "atau tempel kode QRIS-nya (diawali <code>000201</code>).\n\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="admin_pay")]]),
        )
        return True

    if data == "admin_pay_viewqris":
        static = get_setting("pay_qris")
        if not static:
            await query.answer("QRIS pembayaran belum diatur.", show_alert=True)
            return True
        info = summarize_qris(static)
        png = await asyncio.to_thread(render_qr_png, static, "QRIS Pembayaran", info["merchant_name"])
        await replace_with_photo(query, png, f"🏪 <b>{esc(info['merchant_name'])}</b>\n{esc(info['merchant_city'])}",
                                 InlineKeyboardMarkup([[Btn("🔙 Pembayaran", callback_data="admin_pay")]]))
        return True

    if data == "admin_pay_uniq":
        set_setting("pay_unique", "0" if get_setting("pay_unique", "1") == "1" else "1")
        await show_pay_admin(query)
        return True

    if data == "admin_pay_exp":
        admin_state[uid] = {"action": "pay_expire"}
        await edit_or_send(
            query,
            f"{header('⏱️', 'Batas Waktu Pembayaran')}\nSaat ini: <b>{_expire_minutes()} menit</b>.\n\n"
            "Kirim angka menit baru (5 – 1440). Contoh: <code>30</code>\n\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="admin_pay")]]),
        )
        return True

    # ── paket ──
    if data == "admin_plans":
        await _show_plans(query)
        return True

    if data == "admin_plan_add":
        admin_state[uid] = {"action": "plan_add"}
        await edit_or_send(
            query,
            f"{header('➕', 'Tambah Paket')}\nKirim dengan format:\n<code>Nama | Hari | Harga</code>\n\n"
            "Contoh:\n<code>VIP 30 Hari | 30 | 25000</code>\n<code>VIP 7 Hari | 7 | 10k</code>\n\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="admin_plans")]]),
        )
        return True

    m = re.fullmatch(r"admin_plan_(edit|tog|del|delok)_(\d+)", data)
    if m:
        action, pid = m.group(1), int(m.group(2))
        if action == "edit":
            p = get_plan(pid)
            if not p:
                await _show_plans(query)
                return True
            admin_state[uid] = {"action": "plan_edit", "plan_id": pid}
            await edit_or_send(
                query,
                f"{header('✏️', 'Edit Paket')}\nSaat ini: <code>{esc(p['name'])} | {p['days']} | {p['price']}</code>\n\n"
                "Kirim data baru dengan format:\n<code>Nama | Hari | Harga</code>\n\nKetik /cancel untuk batal.",
                InlineKeyboardMarkup([[Btn("❌ Batal", callback_data=f"admin_plan_{pid}")]]),
            )
        elif action == "tog":
            p = get_plan(pid)
            if p:
                set_plan_active(pid, not p["is_active"])
            await _show_plan(query, pid)
        elif action == "del":
            await edit_or_send(
                query, f"{header('🗑️', 'Hapus Paket?')}\nPaket akan dihapus permanen. Riwayat order lama tetap aman.",
                InlineKeyboardMarkup([[Btn("✅ Ya, hapus", callback_data=f"admin_plan_delok_{pid}"), Btn("❌ Batal", callback_data=f"admin_plan_{pid}")]]),
            )
        else:
            delete_plan(pid)
            await _show_plans(query)
        return True

    m = re.fullmatch(r"admin_plan_(\d+)", data)
    if m:
        await _show_plan(query, int(m.group(1)))
        return True

    # ── order ──
    if data == "admin_orders_pending":
        await _show_orders_list(query, ("pending", "verifying"), "Order Menunggu", 0, "admin_pay", None)
        return True

    m = re.fullmatch(r"admin_orders_hist_(\d+)", data)
    if m:
        await _show_orders_list(query, None, "Riwayat Order", int(m.group(1)), "admin_pay", "admin_orders_hist_")
        return True

    m = re.fullmatch(r"admin_ord_(view|ok|no)_(\d+)", data)
    if m:
        action, oid = m.group(1), int(m.group(2))
        if action == "view":
            await _show_order(query, context, oid)
        elif action == "ok":
            ok, info = await approve_and_notify(context.bot, oid, uid)
            await _append_status(query, f"{'✅ Disetujui' if ok else '⚠️'} — {esc(info)}")
        else:
            ok, info = await reject_and_notify(context.bot, oid, uid)
            await _append_status(query, f"{'❌ Ditolak' if ok else '⚠️'} — {esc(info)}")
        return True

    return False


# ── Input teks/gambar dari admin (state) ──────────────────────────────────────

def _parse_plan_line(text: str) -> tuple[str, int, int] | None:
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 3 or not parts[0]:
        return None
    if not parts[1].isdigit() or int(parts[1]) < 1 or int(parts[1]) > 3650:
        return None
    price = parse_amount(parts[2])
    if price is None:
        return None
    return parts[0][:40], int(parts[1]), price


async def handle_state_message(update, context, state: dict) -> bool:
    """Return True jika pesan ini ditangani (state milik modul pembayaran)."""
    action = state.get("action")
    msg = update.effective_message
    uid = update.effective_user.id
    text = (msg.text or "").strip()
    back_pay = InlineKeyboardMarkup([[Btn("💳 Pembayaran", callback_data="admin_pay")]])
    back_plans = InlineKeyboardMarkup([[Btn("📦 Daftar Paket", callback_data="admin_plans")]])

    if action == "pay_qris":
        from user.qris import extract_qris_from_message     # import lokal: hindari circular import
        qris, err = await extract_qris_from_message(msg)
        if err:
            await msg.reply_text(err, parse_mode=ParseMode.HTML)
            return True
        info = summarize_qris(qris)
        set_setting("pay_qris", qris)
        admin_state.pop(uid, None)
        try:
            convert_qris(qris, 10000)
            ok_note = ""
        except QRISError as e:
            ok_note = f"\n⚠️ Tes konversi gagal: {esc(str(e))}"
        await msg.reply_text(
            f"✅ <b>QRIS pembayaran disimpan.</b>\n🏪 {esc(info['merchant_name'])} - {esc(info['merchant_city'])}{ok_note}",
            parse_mode=ParseMode.HTML, reply_markup=back_pay)
        return True

    if action == "pay_expire":
        if not text.isdigit() or not (5 <= int(text) <= 1440):
            await msg.reply_text("❌ Kirim angka 5 – 1440 (menit), atau /cancel.")
            return True
        set_setting("pay_expire_min", int(text))
        admin_state.pop(uid, None)
        await msg.reply_text(f"✅ Batas waktu pembayaran: <b>{int(text)} menit</b>.", parse_mode=ParseMode.HTML, reply_markup=back_pay)
        return True

    if action in ("plan_add", "plan_edit"):
        parsed = _parse_plan_line(text)
        if not parsed:
            await msg.reply_text("❌ Format salah. Gunakan:\n<code>Nama | Hari | Harga</code>\nContoh: <code>VIP 30 Hari | 30 | 25000</code>\n\nAtau /cancel.",
                                 parse_mode=ParseMode.HTML)
            return True
        name, days, price = parsed
        if action == "plan_add":
            pid = add_plan(name, days, price)
            await msg.reply_text(f"✅ Paket <b>{esc(name)}</b> ({days} hari - {rp(price)}) ditambahkan.", parse_mode=ParseMode.HTML, reply_markup=back_plans)
        else:
            pid = state["plan_id"]
            update_plan(pid, name, days, price)
            await msg.reply_text(f"✅ Paket diperbarui: <b>{esc(name)}</b> ({days} hari - {rp(price)}).", parse_mode=ParseMode.HTML, reply_markup=back_plans)
        admin_state.pop(uid, None)
        return True

    return False
