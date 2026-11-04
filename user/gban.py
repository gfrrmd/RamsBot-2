"""
Fitur VIP: GBAN (Global Ban).

Perintah diketik dari akun Telegram user sendiri (session Telethon), di chat mana saja:
  .gban (balas pesan)  |  .gban @username alasan  |  .gban 123456789 alasan
  .ungban              |  .gbanlist

Ban dijalankan di semua supergroup/channel tempat user menjadi admin dengan izin blokir.
Daftar GBAN dan pengaturan disimpan di database lokal per user. Bot kontrol tidak perlu jadi admin.
"""
import asyncio
import html
import re

from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telethon import events, utils
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import DeleteParticipantHistoryRequest
from telethon.tl.types import Channel, User

from client_manager import stop_client_for_user
from database import (
    get_userbot_settings,
    gban_add,
    gban_count,
    gban_has,
    gban_list,
    gban_remove,
    is_subscribed,
    save_userbot_settings,
)
from ui import edit_or_send, header_e

HTML = "html"

USAGE = (
    "ℹ️ <b>Cara pakai</b>\n"
    "<code>.gban</code> (balas pesan target)\n"
    "<code>.gban @username alasan</code>\n"
    "<code>.gban 123456789 alasan</code>"
)
NOT_FOUND = (
    "❌ Target tidak ditemukan.\n"
    "Untuk ID, akunmu harus pernah melihat user itu (misalnya satu grup). "
    "Coba balas pesannya atau pakai @username."
)


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


# ── Operasi ban (Telethon) ────────────────────────────────────────────────────

async def _ban_chats(client) -> list:
    """Semua channel/supergroup tempat akun ini pembuat atau admin dengan izin blokir."""
    out = []
    async for d in client.iter_dialogs():
        e = d.entity
        if not isinstance(e, Channel):
            continue
        rights = getattr(e, "admin_rights", None)
        if getattr(e, "creator", False) or (rights and getattr(rights, "ban_users", False)):
            out.append(e)
    return out


async def _purge_user(client, chat, inp) -> None:
    try:
        for _ in range(50):
            r = await client(DeleteParticipantHistoryRequest(channel=chat, participant=inp))
            if not getattr(r, "offset", 0):
                break
    except Exception:
        pass


async def _ban_in(client, chat, inp, purge: bool = False) -> bool:
    for _ in range(3):
        try:
            await client.edit_permissions(chat, inp, view_messages=False)
            if purge and getattr(chat, "megagroup", False):
                await _purge_user(client, chat, inp)
            return True
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
        except Exception:
            return False
    return False


async def _unban_in(client, chat, inp) -> bool:
    for _ in range(3):
        try:
            await client.edit_permissions(chat, inp, view_messages=True)
            return True
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
        except Exception:
            return False
    return False


async def _resolve_target(client, ev, arg: str):
    """Target dari balasan pesan, username, atau ID. Return (entity|None, sisa_teks)."""
    if ev.is_reply:
        r = await ev.get_reply_message()
        s = await r.get_sender() if r else None
        return s, arg
    if not arg:
        return None, ""
    tok, _, rest = arg.partition(" ")
    ref = int(tok) if re.fullmatch(r"\d+", tok) else tok
    try:
        return await client.get_entity(ref), rest.strip()
    except Exception:
        return None, rest.strip()


# ── Handler Telethon (perintah titik) ─────────────────────────────────────────

def register_gban_handler(client, user_id: int):
    async def vip_ok() -> bool:
        if is_subscribed(user_id):
            return True
        await stop_client_for_user(user_id)
        try:
            await client.send_message("me", "❌ Langganan VIP kamu sudah habis atau dicabut.\nHubungi admin untuk memperpanjang.")
        except Exception:
            pass
        return False

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?is)^\.gban(?:\s+(.+))?$"))
    async def cmd_gban(ev):
        if not await vip_ok():
            return
        arg = (ev.pattern_match.group(1) or "").strip()
        if not arg and not ev.is_reply:
            await ev.edit(USAGE, parse_mode=HTML)
            return
        target, reason = await _resolve_target(client, ev, arg)
        if not isinstance(target, User):
            await ev.edit(NOT_FOUND, parse_mode=HTML)
            return
        me = await client.get_me()
        if target.id == me.id:
            await ev.edit("🙅 Tidak bisa GBAN diri sendiri.", parse_mode=HTML)
            return
        if target.id == 777000:
            await ev.edit("🙅 Akun resmi Telegram tidak bisa di-GBAN.", parse_mode=HTML)
            return
        cfg = get_userbot_settings(user_id)
        name = utils.get_display_name(target) or str(target.id)
        reason = (reason or "")[:200]
        gban_add(user_id, target.id, name[:64], target.username, reason)
        await ev.edit(f"⏳ <b>GBAN</b> {_e(name)}: memindai chat admin...", parse_mode=HTML)
        chats = await _ban_chats(client)
        inp = await client.get_input_entity(target)
        ok = fail = 0
        for i, c in enumerate(chats, 1):
            if await _ban_in(client, c, inp, cfg["purge_on_gban"]):
                ok += 1
            else:
                fail += 1
            await asyncio.sleep(0.4)
            if i % 5 == 0:
                try:
                    await ev.edit(f"⏳ <b>GBAN</b> {_e(name)}\n{i}/{len(chats)} chat diproses...", parse_mode=HTML)
                except Exception:
                    pass
        text = (f"🚫 <b>GBAN SELESAI</b>\n"
                f"👤 {_e(name)}\n🆔 <code>{target.id}</code>\n"
                f"✅ Berhasil: <b>{ok}</b> chat\n⚠️ Gagal/tanpa izin: <b>{fail}</b>")
        if reason:
            text += f"\n📝 Alasan: {_e(reason)}"
        await ev.edit(text, parse_mode=HTML)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?is)^\.ungban(?:\s+(.+))?$"))
    async def cmd_ungban(ev):
        if not await vip_ok():
            return
        arg = (ev.pattern_match.group(1) or "").strip()
        target, _ = await _resolve_target(client, ev, arg)
        if not isinstance(target, User):
            # ID yang tidak bisa dicari tetap dihapus dari daftar bila ada
            if re.fullmatch(r"\d+", arg or "") and gban_remove(user_id, int(arg)):
                await ev.edit(f"✅ ID <code>{_e(arg)}</code> dihapus dari daftar GBAN.\n"
                              "Akun belum dikenali, jadi blokir di chat tidak dibuka. Buka manual bila perlu.",
                              parse_mode=HTML)
            else:
                await ev.edit(NOT_FOUND.replace("GBAN", "UNGBAN"), parse_mode=HTML)
            return
        name = utils.get_display_name(target) or str(target.id)
        gban_remove(user_id, target.id)
        await ev.edit(f"⏳ <b>UNGBAN</b> {_e(name)}: memproses...", parse_mode=HTML)
        chats = await _ban_chats(client)
        inp = await client.get_input_entity(target)
        ok = 0
        for c in chats:
            if await _unban_in(client, c, inp):
                ok += 1
            await asyncio.sleep(0.4)
        await ev.edit(f"✅ <b>UNGBAN SELESAI</b>\n👤 {_e(name)}\n🔓 Dibuka di <b>{ok}</b> chat", parse_mode=HTML)

    @client.on(events.NewMessage(outgoing=True, pattern=r"(?i)^\.gbanlist$"))
    async def cmd_gbanlist(ev):
        if not await vip_ok():
            return
        await ev.edit(f"🚫 <b>DAFTAR GBAN</b> ({gban_count(user_id)})\n{gban_text(user_id, 30)}", parse_mode=HTML)

    @client.on(events.ChatAction)
    async def on_join(ev):
        """Auto-ban: akun di daftar GBAN yang masuk ke chat tempat kamu admin langsung diblokir."""
        try:
            if not (ev.user_joined or ev.user_added):
                return
            chat = await ev.get_chat()
            if not isinstance(chat, Channel):
                return
            rights = getattr(chat, "admin_rights", None)
            if not (getattr(chat, "creator", False) or (rights and rights.ban_users)):
                return
            if not gban_count(user_id):
                return
            cfg = get_userbot_settings(user_id)
            if not cfg["auto_ban"]:
                return
            for u in await ev.get_users():
                if gban_has(user_id, u.id):
                    await _ban_in(client, chat, u, cfg["purge_on_gban"])
        except Exception:
            pass


def gban_text(user_id: int, limit: int = 30) -> str:
    rows = gban_list(user_id, limit)
    if not rows:
        return "Belum ada user di daftar GBAN."
    lines = []
    for d in rows:
        u = f" @{_e(d['username'])}" if d["username"] else ""
        r = f" ({_e(d['reason'])})" if d["reason"] else ""
        lines.append(f"• {_e(d['name'])}{u} <code>{d['target_id']}</code>{r}")
    return "\n".join(lines)


# ── Menu di bot ───────────────────────────────────────────────────────────────

def _onoff(v: bool) -> str:
    return "ON ✅" if v else "OFF ❌"


def _menu_kb(cfg: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [Btn("📋 Daftar GBAN", callback_data="gb_list")],
        [Btn(f"🛡 Auto-ban: {_onoff(cfg['auto_ban'])}", callback_data="gb_auto")],
        [Btn(f"🧹 Hapus pesan target: {_onoff(cfg['purge_on_gban'])}", callback_data="gb_purge")],
        [Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")],
    ])


async def show_gban_menu(query, uid: int):
    cfg = get_userbot_settings(uid)
    text = (
        f"{header_e('🚫', 'GBAN (Global Ban)')}\n"
        "Blokir satu akun sekaligus dari semua grup dan channel tempat kamu menjadi admin.\n\n"
        "📝 <b>Cara pakai</b>\nKetik dari akun Telegram kamu di chat mana saja:\n"
        "<code>.gban</code> (balas pesan target)\n"
        "<code>.gban @username alasan</code>\n"
        "<code>.gban 123456789 alasan</code>\n"
        "<code>.ungban</code> (balas / @username / ID) untuk mencabut\n"
        "<code>.gbanlist</code> untuk melihat daftar\n\n"
        "ℹ️ Berlaku di supergroup/channel tempat kamu admin dengan izin blokir. "
        "Bot ini tidak perlu jadi admin.\n\n"
        f"📋 Terdaftar: <b>{gban_count(uid)}</b> akun\n"
        f"🛡 Auto-ban saat akun GBAN masuk: <b>{_onoff(cfg['auto_ban'])}</b>\n"
        f"🧹 Hapus pesan target saat GBAN: <b>{_onoff(cfg['purge_on_gban'])}</b>"
    )
    await edit_or_send(query, text, _menu_kb(cfg))


async def gban_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = query.from_user.id
    await query.answer()

    if data == "fitur_gban":
        await show_gban_menu(query, uid)
    elif data == "gb_list":
        text = f"{header_e('📋', f'Daftar GBAN ({gban_count(uid)})')}\n{gban_text(uid, 20)}"
        await edit_or_send(query, text, InlineKeyboardMarkup([[Btn("🔙 GBAN", callback_data="fitur_gban")]]))
    elif data in ("gb_auto", "gb_purge"):
        cfg = get_userbot_settings(uid)
        key = "auto_ban" if data == "gb_auto" else "purge_on_gban"
        cfg[key] = not cfg[key]
        save_userbot_settings(uid, cfg)
        await show_gban_menu(query, uid)
