"""
Pembayaran VIP lewat bot.

Alur: pilih paket → bot buat QRIS dinamis (nominal + kode unik opsional)
→ user bayar → kirim bukti → admin Approve/Tolak → VIP aktif / diperpanjang.
Semua pengaturan (QRIS tujuan, paket, harga) diatur admin dari Panel Admin.
"""
import asyncio
import random
import re
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from admin.payments import approve_and_notify, notify_admin_auto_approved, notify_admin_new_proof
from auth.states import applied_promo, clear_input_waits, waiting_code, waiting_payment_proof
from config import ADMIN_CONTACT, ADMIN_ID
from database import (
    active_order_totals,
    bump_ocr_attempts,
    check_promo,
    create_order,
    find_duplicate_proof,
    get_open_order,
    get_order,
    get_plan,
    get_manual_only_users,
    get_plans,
    get_setting,
    get_user_orders,
    set_order_note,
    set_order_proof,
    update_order_status,
)
from keyboards import nav_row, page_info
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
from utils.codes import CodeError, blocked_message, calc_discount, limiter
from utils.qris import QRISError, convert_qris, render_qr_png, summarize_qris
from utils.receipt import ocr_available, sha256_hex, verify_receipt

MAX_PROOF_BYTES = 10 * 1024 * 1024
PLAN_PAGE = 5                 # paket per halaman di menu beli
HIST_PAGE = 5                 # pesanan per halaman di riwayat
MAX_OCR_ATTEMPTS = 3          # percobaan baca otomatis sebelum diteruskan ke admin


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
    if order.get("discount"):
        lines.append(kv("Diskon", f"-{rp(order['discount'])} ({esc(order.get('promo_code'))})"))
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
    home = Btn("🏠 Menu Utama", callback_data="menu_back")
    if order["status"] == "pending":
        rows = [[Btn("📸 Kirim Bukti Bayar", callback_data=f"pay_proof_{oid}")],
                [Btn("❌ Batalkan Pesanan", callback_data=f"pay_cancel_{oid}"), home]]
    elif order["status"] == "verifying":
        rows = [[Btn("🔁 Kirim Ulang Bukti", callback_data=f"pay_proof_{oid}")],
                [Btn("📜 Riwayat", callback_data="pay_history"), home]]
    else:
        rows = [[Btn("💎 Beli Lagi", callback_data="pay_menu"), Btn("📜 Riwayat", callback_data="pay_history")],
                [home]]
    return InlineKeyboardMarkup(rows)


# ── Layar ─────────────────────────────────────────────────────────────────────

def _current_promo(uid: int) -> tuple[dict | None, str | None]:
    """Promo yang terpasang untuk user (divalidasi ulang). Yang sudah tidak valid dilepas + catatan."""
    code = applied_promo.get(uid)
    if not code:
        return None, None
    try:
        return check_promo(code, uid), None
    except CodeError as e:
        applied_promo.pop(uid, None)
        return None, f"⚠️ Kode promo {esc(code)} dilepas: {esc(e.args[0])}"


def _price_text(price: int) -> str:
    return rp(price) if price > 0 else "GRATIS"


def build_pay_menu(uid: int, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    if not payment_ready():
        return (
            f"{header('💎', 'Beli / Perpanjang VIP')}Pembayaran lewat bot belum tersedia saat ini.\n"
            f"Silakan hubungi admin {esc(ADMIN_CONTACT)}.",
            InlineKeyboardMarkup([[Btn("🔙 Kembali", callback_data="menu_back")]]),
        )

    plans = get_plans(active_only=True)
    total = len(plans)
    page = max(0, min(page, max(0, (total - 1) // PLAN_PAGE)))
    promo, note = _current_promo(uid)
    lines = [header("💎", "Beli / Perpanjang VIP").rstrip(), kv("Akun kamu", sub_badge(uid))]
    if promo:
        lines.append(f"🏷️ Promo: <b>{esc(promo['code'])}</b> (diskon {promo['percent']}%)")
    if note:
        lines.append(note)
    rows = []
    open_o = get_open_order(uid)
    if open_o:
        rows.append([Btn(f"🧾 Lanjutkan Pesanan #{open_o['id']} - {rp(open_o['total'])}", callback_data=f"pay_view_{open_o['id']}")])
    lines.append("📦 <b>Pilih paket:</b>")
    for p in plans[page * PLAN_PAGE:(page + 1) * PLAN_PAGE]:
        if promo:
            final = calc_discount(p["price"], promo["percent"])[1]
            lines.append(f"• <b>{esc(p['name'])}</b> — {p['days']} hari — <s>{rp(p['price'])}</s> {_price_text(final)}")
        else:
            final = p["price"]
            lines.append(f"• <b>{esc(p['name'])}</b> — {p['days']} hari — {rp(final)}")
        rows.append([Btn(f"💎 {p['name']} - {_price_text(final)}", callback_data=f"pay_plan_{p['id']}")])
    nav = nav_row("pay_menu_", page, total, PLAN_PAGE)
    if nav:
        rows.append(nav)
        lines.append(page_info(page, total, PLAN_PAGE))
    if promo:
        rows.append([Btn("🏷️ Ganti Promo", callback_data="pay_promo"), Btn("🗑️ Hapus Promo", callback_data="pay_promoclear")])
    else:
        rows.append([Btn("🏷️ Punya Kode Promo?", callback_data="pay_promo")])
    lines += [
        "ℹ️ Perpanjang sebelum habis → sisa hari <b>otomatis ditambahkan</b>.",
        "💳 Bayar pakai QRIS (semua e-wallet &amp; m-banking), lalu kirim bukti bayar. Admin akan memverifikasi.",
    ]
    rows.append([Btn("📜 Riwayat Pesanan", callback_data="pay_history"), Btn("🏠 Menu Utama", callback_data="menu_back")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def show_pay_menu(query, uid: int, page: int = 0):
    text, kb = build_pay_menu(uid, page)
    await edit_or_send(query, text, kb)


async def show_order(query, order: dict):
    try:
        png = await asyncio.to_thread(
            render_qr_png, order["qris_payload"], "QRIS Pembayaran",
            summarize_qris(order["qris_payload"]).get("merchant_name", ""), order["total"])
    except Exception:
        await edit_or_send(query, _order_caption(order) + "\n\n⚠️ Gambar QR gagal dibuat, hubungi admin.", _order_keyboard(order))
        return
    await replace_with_photo(query, png, _order_caption(order), _order_keyboard(order))


async def _finish_free_order(query, uid: int, oid: int, promo: dict):
    """Promo 100%: tidak perlu bayar, pesanan langsung disetujui."""
    await edit_or_send(
        query,
        f"{header('🎉', 'Promo 100% Dipakai')}Kode <b>{esc(promo['code'])}</b> membuat pesanan #{oid} gratis. "
        "VIP kamu sedang diaktifkan.",
        InlineKeyboardMarkup([[Btn("🏠 Menu Utama", callback_data="menu_back")]]),
    )
    bot = query.get_bot()
    ok, info = await approve_and_notify(bot, oid, 0, "promo", f"Kode promo {promo['code']} (100%)")
    if not ok:
        print(f"[payment] order gratis #{oid} gagal disetujui: {info}")
        return
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🏷️ <b>VIP gratis via promo 100%</b>\nUser: <code>{uid}</code>\nKode: {esc(promo['code'])}\n{esc(info)}",
            parse_mode=ParseMode.HTML)
    except Exception:
        pass


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

    promo, discount, price = None, 0, plan["price"]
    code = applied_promo.get(uid)
    if code:
        try:
            promo = check_promo(code, uid)
        except CodeError as e:
            applied_promo.pop(uid, None)
            await query.answer(f"Kode promo dilepas: {e.args[0]}", show_alert=True)
            await show_pay_menu(query, uid)
            return
        discount, price = calc_discount(plan["price"], promo["percent"])

    free = price <= 0
    unique = 0 if free else pick_unique_code(price)
    total = price + unique
    payload = ""
    if not free:
        try:
            payload = convert_qris(static, total)
        except QRISError as e:
            await query.answer(f"QRIS pembayaran bermasalah: {e}", show_alert=True)
            return
    try:
        oid = create_order(uid, plan, unique, total, payload, promo, discount)
    except CodeError as e:                    # kuota promo direbut user lain saat checkout
        applied_promo.pop(uid, None)
        await query.answer(f"Kode promo ditolak: {e.args[0]}", show_alert=True)
        await show_pay_menu(query, uid)
        return
    applied_promo.pop(uid, None)              # promo sudah terpakai pada pesanan ini
    if free:
        await _finish_free_order(query, uid, oid, promo)
        return
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

    if data == "pay_promo":
        wait = limiter.blocked_for(uid)
        if wait:
            await edit_or_send(query, blocked_message(wait), InlineKeyboardMarkup([[Btn("🔙 Kembali", callback_data="pay_menu")]]))
            return
        waiting_code[uid] = "promo"
        await edit_or_send(
            query,
            f"{header('🏷️', 'Kode Promo')}Kirim kode promo kamu sekarang.\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="pay_menu")]]),
        )
        return

    if data == "pay_promoclear":
        applied_promo.pop(uid, None)
        await show_pay_menu(query, uid)
        return

    m = re.fullmatch(r"pay_menu(?:_(\d+))?", data)
    if m:
        await show_pay_menu(query, uid, int(m.group(1) or 0))
        return

    if data.startswith("pay_plan_"):
        await _create_order_flow(query, uid, int(data[len("pay_plan_"):]))
        return

    m = re.fullmatch(r"pay_history(?:_(\d+))?", data)
    if m:
        all_orders = get_user_orders(uid, 200)
        total = len(all_orders)
        page = max(0, min(int(m.group(1) or 0), max(0, (total - 1) // HIST_PAGE)))
        orders = all_orders[page * HIST_PAGE:(page + 1) * HIST_PAGE]
        if not orders:
            body = "Belum ada pesanan."
        else:
            body = "\n".join(
                f"<b>#{o['id']}</b> - {esc(o['plan_name'])} - {rp(o['total'])}\n   {STATUS_LABEL.get(o['status'], o['status'])} - {esc(fmt_date(o['created_at']))}"
                for o in orders)
        rows = []
        nav = nav_row("pay_history_", page, total, HIST_PAGE)
        if nav:
            rows.append(nav)
            body += f"\n\n{page_info(page, total, HIST_PAGE)}"
        rows.append([Btn("💎 Beli / Perpanjang", callback_data="pay_menu"), Btn("🏠 Menu Utama", callback_data="menu_back")])
        await edit_or_send(query, f"{header('📜', 'Riwayat Pesanan')}\n{body}", InlineKeyboardMarkup(rows))
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


async def begin_proof(message, uid: int, order: dict | None) -> bool:
    """
    Mulai mode kirim bukti bayar untuk sebuah pesanan. Dipakai deep link /start pay_<id> dari Mini App,
    sehingga bukti diproses alur yang SAMA dengan bot (OCR auto-verifikasi, cek bukti ganda, wajib-manual).
    Return True jika mode kirim bukti aktif.
    """
    if not order or order["user_id"] != uid:
        await message.reply_text("⚠️ Pesanan tidak ditemukan. Buka menu Beli VIP untuk membuat pesanan baru.")
        return False
    if order["status"] == "pending" and datetime.now() > _deadline(order):
        update_order_status(order["id"], "expired", ("pending",))
        await message.reply_text("⚠️ Pesanan sudah kedaluwarsa. Silakan buat pesanan baru.")
        return False
    if order["status"] not in ("pending", "verifying"):
        await message.reply_text(f"ℹ️ Pesanan #{order['id']} berstatus {STATUS_LABEL.get(order['status'], order['status'])}.")
        return False
    waiting_payment_proof[uid] = order["id"]
    await message.reply_text(
        f"📸 <b>Kirim bukti pembayaran</b> (pesanan #{order['id']})\n\nKirim screenshot / foto bukti transfer sekarang "
        f"(total <b>{rp(order['total'])}</b>).\nKetik /cancel untuk batal.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="pay_cancelproof")]]),
    )
    return True


# ── Terima bukti bayar ────────────────────────────────────────────────────────

def _auto_verify_active(uid: int) -> bool:
    """Auto-verifikasi berjalan jika: diaktifkan admin, OCR terpasang, dan user tidak ditandai wajib-manual."""
    return get_setting("pay_auto", "0") == "1" and ocr_available() and uid not in get_manual_only_users()


def _tz_offset() -> int:
    try:
        return max(-12, min(14, int(get_setting("pay_tz_offset", "7"))))
    except ValueError:
        return 7


async def _forward_to_admin(context, msg, user, oid: int, file_ref: str, digest: str | None, note: str | None):
    """Jalur manual: simpan bukti, status 'verifying', minta admin memutuskan."""
    if not set_order_proof(oid, file_ref, digest, "verifying"):
        await msg.reply_text("⚠️ Pesanan sudah diproses.")
        return
    waiting_payment_proof.pop(user.id, None)
    if note:
        set_order_note(oid, note)
    await msg.reply_text(
        f"✅ <b>Bukti pembayaran diterima</b> (pesanan #{oid}).\n\nAdmin akan segera memverifikasi. "
        "Kamu akan mendapat notifikasi otomatis begitu VIP aktif. 🙏",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[Btn("🏠 Menu Utama", callback_data="menu_back")]]),
    )
    await notify_admin_new_proof(context.bot, get_order(oid), user, note)


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
    file_ref = f"{kind}:{obj.file_id}"

    # Unduh gambar: dipakai untuk hash (anti bukti dipakai ulang) dan OCR.
    data, digest = None, None
    try:
        tg_file = await obj.get_file()
        data = bytes(await tg_file.download_as_bytearray())
        digest = sha256_hex(data)
    except Exception as e:
        print(f"[payment] gagal unduh bukti order #{oid}: {e}")

    notes: list[str] = []
    dup = find_duplicate_proof(digest, oid) if digest else None
    if dup:
        notes.append(f"Gambar bukti IDENTIK dengan order #{dup['id']} (user {dup['user_id']}, status {dup['status']}) "
                     "— kemungkinan bukti dipakai ulang.")

    auto = _auto_verify_active(uid)
    if not auto or data is None or dup:
        if auto and data is None:
            notes.append("Gambar gagal diunduh untuk OCR.")
        await _forward_to_admin(context, msg, user, oid, file_ref, digest, " ".join(notes) or None)
        return

    # ── Auto-verifikasi (OCR) ──
    wait_msg = await msg.reply_text("🔎 Membaca bukti pembayaran...")
    created = datetime.fromisoformat(order["created_at"])
    res = await verify_receipt(data, order["total"], created, _deadline(order), _tz_offset())
    try:
        await wait_msg.delete()
    except Exception:
        pass

    if res.status == "match":
        if not set_order_proof(oid, file_ref, digest, "verifying"):
            waiting_payment_proof.pop(uid, None)
            await msg.reply_text("⚠️ Pesanan sudah diproses.")
            return
        waiting_payment_proof.pop(uid, None)
        ok, info = await approve_and_notify(context.bot, oid, 0, "auto", res.note)
        if ok:
            await notify_admin_auto_approved(context.bot, get_order(oid), res.note)
        else:
            await msg.reply_text("⚠️ Pesanan sudah diproses.")
        return

    if res.status in ("amount_mismatch", "unreadable"):
        attempts = bump_ocr_attempts(oid)
        if attempts < MAX_OCR_ATTEMPTS and order["status"] == "pending":
            set_order_proof(oid, file_ref, digest, "pending")        # tetap menunggu; user boleh kirim ulang
            left = MAX_OCR_ATTEMPTS - attempts
            await msg.reply_text(
                f"⚠️ <b>Nominal pada bukti belum terbaca / tidak cocok.</b>\n\n"
                f"Pastikan screenshot menampilkan nominal <b>{rp(order['total'])}</b> dengan jelas "
                "(seluruh layar, tidak terpotong atau buram), lalu kirim ulang.\n"
                f"Sisa percobaan otomatis: {left}. Ketik /cancel untuk batal.",
                parse_mode=ParseMode.HTML,
            )
            return
        notes.append(f"{res.note} (OCR gagal setelah {attempts} percobaan)")
    else:                                                            # time_mismatch | error
        notes.append(res.note)
    await _forward_to_admin(context, msg, user, oid, file_ref, digest, " ".join(notes))
