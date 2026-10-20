"""
Token VIP (pindahkan VIP ke akun lain), klaim voucher, dan penerima input kode user.

Token: diterbitkan setiap pembelian VIP, kode acak RMS-XXXX-XXXX-XXXX, maksimal 3x pakai.
Saat dipakai di akun baru, sisa masa VIP berpindah, akun lama dinonaktifkan, dan token ikut
berpindah ke akun baru. Pembelian VIP berikutnya menerbitkan kode baru dan mereset pemakaian.
"""
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from auth.states import applied_promo, clear_input_waits, waiting_code
from client_manager import stop_client_for_user
from config import ADMIN_CONTACT, ADMIN_ID
from database import check_promo, claim_voucher, ensure_token, transfer_vip_by_token, upsert_user
from services.session_runner import ensure_client_running
from ui import edit_or_send, esc, fmt_dt, get_sub_state, header, token_notice
from utils.codes import (
    CodeError,
    blocked_message,
    limiter,
    normalize_code,
    normalize_token,
)

HTML = ParseMode.HTML
_HOME = Btn("🏠 Menu Utama", callback_data="menu_back")
_AFTER_KB = InlineKeyboardMarkup([[Btn("✨ Setup Bot", callback_data="menu_setup")], [_HOME]])
_MENU_KB = InlineKeyboardMarkup([[_HOME]])

_TOKEN_ERRORS = {
    "limit": "❌ Token ini sudah dipakai sampai batas maksimal. Beli VIP periode berikutnya untuk mendapatkan token baru.",
    "inactive": "❌ VIP pada token ini sudah habis atau tidak aktif, jadi tidak bisa dipindahkan.",
    "target_active": "⚠️ Akun ini masih punya VIP aktif. Token hanya bisa dipakai di akun tanpa VIP aktif.",
    "same": "⚠️ Token ini sudah terpasang di akun ini.",
}


def _active_vip(uid: int) -> bool:
    s = get_sub_state(uid)
    return s["state"] == "active" and s["plan"] == "vip"


def _session_note(sess: str) -> str:
    if sess in ("started", "already"):
        return "🔌 Session akun ini otomatis aktif kembali, fitur siap dipakai."
    if sess == "no_session":
        return "✨ Tekan <b>Setup Bot</b> untuk menghubungkan akun ini."
    return "⚠️ Session lama tidak bisa dijalankan. Tekan <b>Setup Bot</b> untuk login ulang."


# ── Layar token ───────────────────────────────────────────────────────────────

def build_token_screen(uid: int) -> tuple[str, InlineKeyboardMarkup]:
    if _active_vip(uid):
        tok = ensure_token(uid)
        if tok:
            left = max(0, tok["max_uses"] - tok["uses"])
            lines = [
                header("🔑", "Token VIP").rstrip(),
                "Kode token kamu:",
                f"<code>{tok['token']}</code>",
                f"Pemakaian: {tok['uses']} dari {tok['max_uses']} kali (sisa {left})",
                "Token dipakai untuk memindahkan VIP ke akun Telegram lain jika akun ini terkena banned, "
                "tanpa perlu beli VIP lagi.",
                "⚠️ Simpan kode ini di tempat aman di luar akun ini (catatan HP atau password manager) "
                "dan jangan bagikan ke siapa pun.",
                "Kode berganti dan pemakaian kembali ke 0 saat kamu membeli VIP periode berikutnya.",
            ]
            if left == 0:
                lines.append("Batas pemakaian sudah habis. Beli VIP periode berikutnya untuk mendapatkan token baru.")
            return "\n".join(lines), InlineKeyboardMarkup([[_HOME]])
    text = (
        header("🔑", "Token VIP")
        + "Punya kode token dari pembelian VIP sebelumnya? Masukkan kodenya untuk memindahkan sisa VIP ke akun ini.\n"
        "Setiap token bisa dipakai maksimal 3 kali, dan VIP di akun lama akan dinonaktifkan."
    )
    return text, InlineKeyboardMarkup([
        [Btn("🔑 Masukkan Token", callback_data="tok_enter")],
        [Btn("💎 Beli VIP", callback_data="pay_menu"), _HOME],
    ])


# ── Callback ──────────────────────────────────────────────────────────────────

async def codes_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    data = query.data
    await query.answer()
    clear_input_waits(uid)

    if data == "tok_menu":
        text, kb = build_token_screen(uid)
        await edit_or_send(query, text, kb)
        return

    if data == "tok_enter":
        if _active_vip(uid):                      # akun ini sudah VIP: tampilkan token miliknya saja
            text, kb = build_token_screen(uid)
            await edit_or_send(query, text, kb)
            return
        wait = limiter.blocked_for(uid)
        if wait:
            await edit_or_send(query, blocked_message(wait), _MENU_KB)
            return
        waiting_code[uid] = "token"
        await edit_or_send(
            query,
            header("🔑", "Masukkan Token")
            + "Kirim kode token kamu sekarang.\nContoh: <code>RMS-ABCD-EFGH-JKLM</code>\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="tok_menu")]]),
        )
        return

    if data == "vch_enter":
        wait = limiter.blocked_for(uid)
        if wait:
            await edit_or_send(query, blocked_message(wait), _MENU_KB)
            return
        waiting_code[uid] = "voucher"
        await edit_or_send(
            query,
            header("🎟️", "Klaim Voucher") + "Kirim kode voucher kamu sekarang.\nKetik /cancel untuk batal.",
            InlineKeyboardMarkup([[Btn("❌ Batal", callback_data="menu_back")]]),
        )
        return


# ── Penerima input kode ───────────────────────────────────────────────────────

async def handle_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, user = update.effective_message, update.effective_user
    uid = user.id
    kind = waiting_code.get(uid)
    if not kind:
        return
    text = (msg.text or "").strip()
    if not text:
        await msg.reply_text("⚠️ Kirim kode dalam bentuk teks, atau ketik /cancel untuk batal.")
        return
    wait = limiter.blocked_for(uid)
    if wait:
        waiting_code.pop(uid, None)
        await msg.reply_text(blocked_message(wait), reply_markup=_MENU_KB)
        return
    upsert_user(uid, user.username, user.full_name)
    if kind == "token":
        await _redeem_token(msg, context, user, text)
    elif kind == "voucher":
        await _claim_voucher(msg, context, user, text)
    elif kind == "promo":
        await _apply_promo(msg, user, text)


async def _code_rejected(msg, uid: int, err: CodeError):
    """Kode tidak dikenal: boleh coba lagi (dihitung tebakan salah). Alasan lain: selesai."""
    if err.not_found:
        limiter.fail(uid)
        await msg.reply_text(f"❌ {err.args[0]}\nCoba lagi atau ketik /cancel untuk batal.")
        return
    waiting_code.pop(uid, None)
    await msg.reply_text(f"❌ {err.args[0]}", reply_markup=_MENU_KB)


async def _redeem_token(msg, context, user, text: str):
    uid = user.id
    code = normalize_token(text)
    if not code:
        limiter.fail(uid)
        await msg.reply_text(
            "❌ Format token tidak valid.\nContoh: <code>RMS-ABCD-EFGH-JKLM</code>\nCoba lagi atau ketik /cancel untuk batal.",
            parse_mode=HTML)
        return
    res = transfer_vip_by_token(code, uid)
    if not res["ok"]:
        if res["error"] == "invalid":
            limiter.fail(uid)
            await msg.reply_text("❌ Token tidak ditemukan. Periksa kembali kodenya atau ketik /cancel untuk batal.")
            return
        waiting_code.pop(uid, None)
        await msg.reply_text(_TOKEN_ERRORS[res["error"]], reply_markup=_MENU_KB)
        return

    limiter.reset(uid)
    waiting_code.pop(uid, None)
    old_id = res["from_id"]
    await stop_client_for_user(old_id)
    sess = await ensure_client_running(uid, context.bot)
    left = res["max_uses"] - res["uses"]
    lines = [
        header("✅", "VIP Berhasil Dipindahkan").rstrip(),
        f"VIP aktif sampai <b>{esc(fmt_dt(res['expired']))}</b>",
        f"Pemakaian token: {res['uses']} dari {res['max_uses']} kali" + (f" (sisa {left})" if left else " (batas habis)"),
        "VIP di akun lama sudah dinonaktifkan.",
        _session_note(sess),
        "Kode token tetap sama, simpan baik-baik di luar akun ini:",
        f"<code>{res['token']}</code>",
    ]
    if left == 0:
        lines.append("Beli VIP periode berikutnya untuk mendapatkan token baru.")
    await msg.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=_AFTER_KB)

    try:
        await context.bot.send_message(
            old_id,
            "ℹ️ VIP akun ini telah dipindahkan ke akun lain menggunakan token. "
            f"Jika bukan kamu yang melakukannya, segera hubungi admin {ADMIN_CONTACT}.")
    except Exception:
        pass                                           # akun lama mungkin sudah banned / memblokir bot
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"🔑 <b>Token dipakai</b>\nDari: <code>{old_id}</code>\n"
            f'Ke: <a href="tg://user?id={uid}">{esc(user.full_name)}</a> <code>{uid}</code>\n'
            f"Pemakaian: {res['uses']}/{res['max_uses']}\nVIP s/d {esc(fmt_dt(res['expired']))}",
            parse_mode=HTML)
    except Exception:
        pass


async def _claim_voucher(msg, context, user, text: str):
    uid = user.id
    code = normalize_code(text)
    if not code:
        limiter.fail(uid)
        await msg.reply_text("❌ Format kode tidak valid. Coba lagi atau ketik /cancel untuk batal.")
        return
    try:
        res = claim_voucher(code, uid)
    except CodeError as e:
        await _code_rejected(msg, uid, e)
        return
    limiter.reset(uid)
    waiting_code.pop(uid, None)
    sess = await ensure_client_running(uid, context.bot)
    await msg.reply_text(
        header("🎉", "Voucher Berhasil Diklaim")
        + f"Tambahan: {res['days']} hari\n"
        f"VIP aktif sampai: <b>{esc(fmt_dt(res['expired']))}</b>\n"
        f"{_session_note(sess)}\n"
        f"{token_notice(res['token'])}",
        parse_mode=HTML, reply_markup=_AFTER_KB)


async def _apply_promo(msg, user, text: str):
    from user.payment import build_pay_menu              # import lokal: hindari circular import
    uid = user.id
    code = normalize_code(text)
    if not code:
        limiter.fail(uid)
        await msg.reply_text("❌ Format kode tidak valid. Coba lagi atau ketik /cancel untuk batal.")
        return
    try:
        promo = check_promo(code, uid)
    except CodeError as e:
        await _code_rejected(msg, uid, e)
        return
    limiter.reset(uid)
    waiting_code.pop(uid, None)
    applied_promo[uid] = promo["code"]
    pay_text, kb = build_pay_menu(uid)
    await msg.reply_text(pay_text, parse_mode=HTML, reply_markup=kb, disable_web_page_preview=True)
