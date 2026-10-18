"""
Pembayaran VIP lewat bot.

Alur: pilih paket → bot buat QRIS dinamis (nominal + kode unik opsional)
→ user bayar → kirim bukti → admin Approve/Tolak → VIP aktif / diperpanjang.
Semua pengaturan (QRIS tujuan, paket, harga) diatur admin dari Panel Admin.
"""
import asyncio
import random
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from admin.payments import notify_admin_new_proof
from auth.states import clear_input_waits, waiting_payment_proof
from config import ADMIN_CONTACT
from database import (
    active_order_totals,
    create_order,
    get_open_order,
    get_order,
    get_plan,
    get_plans,
    get_setting,
    get_user_orders,
    set_order_proof,
    update_order_status,
)
from ui import (
    STATUS_LABEL,
    edit_or_send,
    esc,
    fmt_date,
    fmt_dt,
    header,
    kv,
    replace_with_photo,
    rp,
    sub_badge,
)
from utils.qris import QRISError, convert_qris, render_qr_png, summarize_qris

MAX_PROOF_BYTES = 10 * 1024 * 1024


# ── Util ──────────────────────────────────────────────────────────────────────

def order_expire_minutes() -> int:
    try:
        return max(5, int(get_setting("pay_expire_min", "60")))
    except ValueError:
        return 60


def payment_ready() -> bool:
    return bool(get_setting("pay_qris")) and bool(get_plans(active_only=True))


def pick_unique_code(base_price: int) -> int:
    """Kode unik 1–99 agar admin mudah mencocokkan nominal masuk. 0 jika dimatikan."""
    if get_setting("pay_unique", "1") != "1":
        return 0
    taken = active_order_totals()
    codes = list(range(1, 100))
    random.shuffle(codes)
    for c in codes:
        if base_price + c not in taken:
            return c
    return 0


def _deadline(order: dict) -> datetime:
    return datetime.fromisoformat(order["created_at"]) + timedelta(minutes=order_expire_minutes())


def _order_caption(order: dict) -> str:
    merchant = summarize_qris(order["qris_payload"]).get("merchant_name", "") if order.get("qris_payload") else ""
    lines = [
        header("🧾", f"Pesanan #{order['id']}"),
        kv("Paket", f"{esc(order['plan_name'])} ({order['days']} hari)"),
        kv("Harga", rp(order["base_price"])),
    ]
    if order["unique_code"]:
        lines.append(kv("Kode unik", f"+{rp(order['unique_code'])}"))
    lines.append(kv("Total", f"<b>{rp(order['total'])}</b>"))
    if merchant:
        lines.append(kv("Merchant", esc(merchant)))
    lines.append(kv("Status", STATUS_LABEL.get(order["status"], order["status"])))
    if order["status"] == "pending":
        lines.append(kv("Bayar s/d", esc(fmt_dt(_deadline(order)))))
        lines.append(f"\nScan QRIS di atas lalu bayar <b>tepat sesuai total</b> (jangan dibulatkan). "
                     "Setelah bayar, tekan <b>Kirim Bukti Bayar</b>.")
    elif order["status"] == "verifying":
        lines.append(f"\nBukti sudah diterima. Admin akan memverifikasi — kamu akan mendapat notifikasi otomatis.")
    return "\n".join(lines)


def _order_keyboard(order: dict) -> InlineKeyboardMarkup:
    oid = order["id"]
    if order["status"] == "pending":
        rows = [[Btn("📸 Kirim Bukti Bayar", callback_data=f"pay_proof_{oid}")],
                [Btn("❌ Batalkan Pesanan", callback_data=f"pay_cancel_{oid}")]]
    elif order["status"] == "verifying":
        rows = [[Btn("🔁 Kirim Ulang Bukti", callback_data=f"pay_proof_{oid}")]]
    else:
        rows = [[Btn("💎 Beli Lagi", callback_data="pay_menu")]]
    rows.append([Btn("🏠 Menu Utama", callback_data="menu_back")])
    return InlineKeyboardMarkup(rows)


# ── Layar ─────────────────────────────────────────────────────────────────────

async def show_pay_menu(query, uid: int):
    if not payment_ready():
        await edit_or_send(
            query,
            f"{header('💎', 'Beli / Perpanjang VIP')}\nPembayaran lewat bot belum tersedia saat ini.\n"
            f"Silakan hubungi admin {esc(ADMIN_CONTACT)}.",
            InlineKeyboardMarkup([[Btn("🔙 Kembali", callback_data="menu_back")]]),
        )
        return

    plans = get_plans(active_only=True)
    lines = [header("💎", "Beli / Perpanjang VIP"), kv("Akun kamu", sub_badge(uid), 10), ""]
    rows = []
    open_o = get_open_order(uid)
    if open_o:
        rows.append([Btn(f"🧾 Lanjutkan Pesanan #{open_o['id']} - {rp(open_o['total'])}", callback_data=f"pay_view_{open_o['id']}")])
    lines.append("📦 <b>Pilih paket:</b>")
    for p in plans:
        lines.append(f"• <b>{esc(p['name'])}</b> — {p['days']} hari — {rp(p['price'])}")
        rows.append([Btn(f"💎 {p['name']} - {rp(p['price'])}", callback_data=f"pay_plan_{p['id']}")])
    lines += [
        "",
        "ℹ️ Perpanjang sebelum habis → sisa hari <b>otomatis ditambahkan</b>.",
        "💳 Bayar pakai QRIS (semua e-wallet &amp; m-banking), lalu kirim bukti bayar. Admin akan memverifikasi.",
    ]
    rows.append([Btn("📜 Riwayat Pesanan", callback_data="pay_history"), Btn("🏠 Menu Utama", callback_data="menu_back")])
    await edit_or_send(query, "\n".join(lines), InlineKeyboardMarkup(rows))


async def show_order(query, order: dict):
    try:
        png = await asyncio.to_thread(
            render_qr_png, order["qris_payload"], "QRIS Pembayaran",
            summarize_qris(order["qris_payload"]).get("merchant_name", ""), order["total"])
    except Exception:
        await edit_or_send(query, _order_caption(order) + "\n\n⚠️ Gambar QR gagal dibuat, hubungi admin.", _order_keyboard(order))
        return
    await replace_with_photo(query, png, _order_caption(order), _order_keyboard(order))


async def _create_order_flow(query, uid: int, plan_id: int):
    plan = get_plan(plan_id)
    static = get_setting("pay_qris")
    if not plan or not plan["is_active"] or not static:
        await query.answer("Paket tidak tersedia.", show_alert=True)
        await show_pay_menu(query, uid)
        return

    open_o = get_open_order(uid)
    if open_o:
        if open_o["status"] == "verifying":
            await query.answer(f"Pesanan #{open_o['id']} sedang diverifikasi admin.", show_alert=True)
            await show_order(query, open_o)
            return
        update_order_status(open_o["id"], "cancelled", ("pending",))     # ganti pesanan lama

    code = pick_unique_code(plan["price"])
    total = plan["price"] + code
    try:
        payload = convert_qris(static, total)
    except QRISError as e:
        await query.answer(f"QRIS pembayaran bermasalah: {e}", show_alert=True)
        return
    oid = create_order(uid, plan, code, total, payload)
    await show_order(query, get_order(oid))


# ── Callback router ───────────────────────────────────────────────────────────

async def payment_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()

    if data == "pay_cancelproof":
        clear_input_waits(uid)
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    clear_input_waits(uid)

    if data == "pay_menu":
        await show_pay_menu(query, uid)
        return

    if data.startswith("pay_plan_"):
        await _create_order_flow(query, uid, int(data[len("pay_plan_"):]))
        return

    if data == "pay_history":
        orders = get_user_orders(uid, 8)
        if not orders:
            body = "Belum ada pesanan."
        else:
            body = "\n".join(
                f"<b>#{o['id']}</b> - {esc(o['plan_name'])} - {rp(o['total'])}\n   {STATUS_LABEL.get(o['status'], o['status'])} - {esc(fmt_date(o['created_at']))}"
                for o in orders)
        await edit_or_send(query, f"{header('📜', 'Riwayat Pesanan')}\n{body}",
                           InlineKeyboardMarkup([[Btn("💎 Beli / Perpanjang", callback_data="pay_menu")],
                                                 [Btn("🏠 Menu Utama", callback_data="menu_back")]]))
        return

    # Aksi pada order tertentu
    try:
        action, oid = data.rsplit("_", 1)
        oid = int(oid)
    except ValueError:
        return
    order = get_order(oid)
    if not order or order["user_id"] != uid:
        await query.answer("Pesanan tidak ditemukan.", show_alert=True)
        return

    if action == "pay_view":
        await show_order(query, order)
        return

    if action == "pay_cancel":
        if order["status"] == "pending":
            update_order_status(oid, "cancelled", ("pending",))
        elif order["status"] == "verifying":
            await query.answer("Pesanan sedang diverifikasi admin, tidak bisa dibatalkan.", show_alert=True)
            return
        await show_pay_menu(query, uid)
        return

    if action == "pay_proof":
        if order["status"] == "pending" and datetime.now() > _deadline(order):
            update_order_status(oid, "expired", ("pending",))
            await query.answer("Pesanan kedaluwarsa. Silakan buat pesanan baru.", show_alert=True)
            await show_pay_menu(query, uid)
            return
        if order["status"] not in ("pending", "verifying"):
            await query.answer(f"Pesanan {STATUS_LABEL.get(order['status'], order['status'])}.", show_alert=True)
            return
        waiting_payment_proof[uid] = oid
        await query.message.reply_text(
            "📸 <b>Kirim bukti pembayaran</b>\n\nKirim screenshot / foto bukti transfer sekarang "
            f"(total <b>{rp(order['total'])}</b>).\nKetik /cancel untuk batal.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="pay_cancelproof")]]),
        )
        return


# ── Terima bukti bayar ────────────────────────────────────────────────────────

async def handle_proof_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    uid = user.id
    oid = waiting_payment_proof.get(uid)
    order = get_order(oid) if oid else None
    if not order or order["user_id"] != uid or order["status"] not in ("pending", "verifying"):
        waiting_payment_proof.pop(uid, None)
        await msg.reply_text("⚠️ Pesanan tidak aktif. Buka menu Beli VIP untuk membuat pesanan baru.")
        return

    if msg.photo:
        kind, obj = "photo", msg.photo[-1]
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        kind, obj = "document", msg.document
    else:
        await msg.reply_text("⚠️ Kirim bukti dalam bentuk <b>foto / screenshot</b>. /cancel untuk batal.", parse_mode=ParseMode.HTML)
        return
    if (obj.file_size or 0) > MAX_PROOF_BYTES:
        await msg.reply_text("❌ Ukuran gambar terlalu besar (maks 10 MB).")
        return

    if not set_order_proof(oid, f"{kind}:{obj.file_id}"):
        waiting_payment_proof.pop(uid, None)
        await msg.reply_text("⚠️ Pesanan sudah diproses.")
        return
    waiting_payment_proof.pop(uid, None)

    await msg.reply_text(
        f"✅ <b>Bukti pembayaran diterima</b> (pesanan #{oid}).\n\nAdmin akan segera memverifikasi. "
        "Kamu akan mendapat notifikasi otomatis begitu VIP aktif. 🙏",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[Btn("🏠 Menu Utama", callback_data="menu_back")]]),
    )
    await notify_admin_new_proof(context.bot, get_order(oid), user)
