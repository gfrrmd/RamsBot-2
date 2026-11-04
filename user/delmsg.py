"""
Fitur VIP: Hapus Pesan.

Semua dikendalikan lewat menu bot (🎯 Fitur VIP → 🗑 Hapus Pesan), pesan dihapus memakai
session Telethon milik user. Pilihan sumber:
  📌 1 chat tertentu  |  👥 semua grup  |  📢 semua channel  |  💬 semua chat pribadi (dua arah)
  💭 komentar di channel (grup diskusi, walau tidak di-join)  |  👥💭 grup + komentar sekaligus
Ada pengecualian per kategori, rentang waktu, 3 pilihan kecepatan, dan tombol hentikan.
Pengaturan tersimpan per user di database lokal.
"""
import asyncio
import html
import re
import time
import traceback
from datetime import datetime, timedelta, timezone

from telegram import CallbackQuery, InlineKeyboardButton as Btn, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.error import RetryAfter
from telegram.ext import ContextTypes
from telethon import utils
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest, GetLeftChannelsRequest
from telethon.tl.types import Channel, User

from auth.states import delmsg_wait
from client_manager import active_clients
from database import get_userbot_settings, save_userbot_settings
from keyboards import back_to_fitur_keyboard
from ui import edit_or_send, header_e

WIB = timezone(timedelta(hours=7))

SPEEDS = {
    "safe": (1.5, "🐢 Aman"),
    "normal": (0.8, "🚶 Normal"),
    "fast": (0.3, "🚀 Cepat"),
}
CATS = {"group": "👥 Grup", "channel": "📢 Channel", "pm": "💬 Pribadi"}
ICON = {"pm": "💬", "group": "👥", "channel": "📢"}
RANGES = {"today": "📅 Hari ini", "week": "🗓 7 hari terakhir", "all": "♾ Semua waktu"}
SCOPES = {
    "one": "📌 1 chat tertentu", "groups": "👥 Semua grup", "channels": "📢 Semua channel",
    "pm": "💬 Semua chat pribadi", "comments": "💭 Komentar di channel", "groupsall": "👥💭 Grup + komentar",
}
MODES = {
    "both": "🔁 Dua arah (semua pesan, hilang di kedua sisi)",
    "mine": "👤 Hanya pesanku",
}
PER_PAGE = 8


def _e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _h(title: str) -> str:
    """Judul tebal tanpa garis pemisah."""
    return f"<b>{_e(title)}</b>\n"


def _fmt_t(sec) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}j {m}m {s}d" if h else (f"{m}m {s}d" if m else f"{s}d")


def _kind_of(ent) -> str:
    if isinstance(ent, User):
        return "pm"
    if isinstance(ent, Channel):
        return "channel" if (ent.broadcast and not ent.megagroup) else "group"
    return "group"


# ── State per user (di memori; hilang saat bot restart, aman) ─────────────────

class Job:
    def __init__(self):
        self.stop = asyncio.Event()
        self.scanned = self.deleted = self.errors = 0
        self.cur = "-"
        self.idx = self.total = 0
        self.done = False
        self.t0 = time.time()
        self.task = None


_STATE: dict[int, dict] = {}


def _st(uid: int) -> dict:
    return _STATE.setdefault(uid, {"wiz": {}, "dlgs": [], "view": [], "pick": "del", "page": 0,
                                   "cat": "group", "job": None})


def _client(uid: int):
    c = active_clients.get(uid)
    return c if c and c.is_connected() else None


def _cutoff_for(r: str):
    if r == "all":
        return None
    now = datetime.now(WIB)
    if r == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now - timedelta(days=7)


# ── Tampilan ──────────────────────────────────────────────────────────────────

async def _show(target, text: str, kb: InlineKeyboardMarkup | None = None):
    """Edit pesan bila dari tombol, kirim pesan baru bila dari teks."""
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, kb)
    else:
        await target.chat.send_message(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                       disable_web_page_preview=True)


def _rows(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(r) for r in rows])


_BACK_FITUR = Btn("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")


async def del_menu(target, uid: int):
    st = _st(uid)
    delmsg_wait.pop(uid, None)
    st["wiz"] = {}
    st["pick"] = "del"
    st["dlgs"], st["view"] = [], []          # bebaskan memori daftar chat
    cfg = get_userbot_settings(uid)
    n_ex = len(cfg["exclude"])
    body = (
        f"{header_e('🗑', 'Hapus Pesan')}\n"
        "Bersihkan pesan kamu dari grup, channel, atau chat pribadi sekaligus.\n\n"
        "📝 <b>Cara pakai</b>\nPilih sumber di bawah, lalu rentang waktu, lalu konfirmasi.\n"
        "📌 <b>1 chat</b>: pilih dari daftar, cari nama, atau kirim @username / ID\n"
        "👥 <b>Grup</b>: hanya pesanmu\n"
        "📢 <b>Channel</b>: hanya postinganmu\n"
        "💭 <b>Komentar channel</b>: balasanmu di grup diskusi\n"
        "💬 <b>Pribadi</b>: bisa dua arah (hilang di kedua sisi)\n"
        "🛡 <b>Pengecualian</b>: chat yang tidak boleh ikut terhapus\n\n"
        "💡 <b>Tips</b>\n"
        "• Di grup kamu hanya bisa menghapus pesan sendiri (kecuali admin berizin hapus)\n"
        "• Untuk proses besar pakai kecepatan Aman agar akun tidak kena limit\n"
        "• Aksi hapus tidak bisa dibatalkan\n\n"
        f"🛡 Pengecualian aktif: <b>{n_ex}</b> chat\n"
        f"⚡ Kecepatan: <b>{SPEEDS[cfg['speed']][1]}</b>"
    )
    kb = _rows(
        [Btn(SCOPES["one"], callback_data="dm_scope_one")],
        [Btn("👥 Semua grup", callback_data="dm_scope_groups"), Btn("📢 Semua channel", callback_data="dm_scope_channels")],
        [Btn("💭 Komentar channel", callback_data="dm_cm"), Btn("👥💭 Grup + komentar", callback_data="dm_scope_groupsall")],
        [Btn("💬 Semua chat pribadi", callback_data="dm_scope_pm")],
        [Btn(f"🛡 Pengecualian ({n_ex})", callback_data="dm_ex"), Btn(f"⚡ {SPEEDS[cfg['speed']][1]}", callback_data="dm_speed")],
        [_BACK_FITUR],
    )
    await _show(target, body, kb)


async def _load_dialogs(client, st: dict, limit: int = 1500):
    out = []
    async for d in client.iter_dialogs(limit=limit):
        ent = d.entity
        if getattr(ent, "is_self", False) or d.id == 777000:
            continue
        out.append((ent, utils.get_display_name(ent) or str(d.id), _kind_of(ent)))
    st["dlgs"] = out
    return out


def _cat_items(st: dict):
    return [x for x in st["dlgs"] if x[2] == st["cat"]]


async def _show_picker(target, uid: int, items, page: int = 0):
    st = _st(uid)
    cfg = get_userbot_settings(uid)
    excl = cfg["exclude"]
    st["view"] = items
    mode = st["pick"]
    pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, pages - 1))
    st["page"] = page
    rows = [[Btn(("• " if st["cat"] == k else "") + f"{lbl} {sum(1 for x in st['dlgs'] if x[2] == k)}",
                 callback_data=f"dm_cat_{k}") for k, lbl in CATS.items()]]
    for i, (e, t, k) in list(enumerate(items))[page * PER_PAGE:(page + 1) * PER_PAGE]:
        mark = "🛡 " if (mode == "ex" and str(utils.get_peer_id(e)) in excl) else ""
        rows.append([Btn(f"{mark}{ICON[k]} {t[:28]}", callback_data=f"dm_pk_{i}")])
    nav = []
    if page > 0:
        nav.append(Btn("⬅️", callback_data=f"dm_pg_{page - 1}"))
    nav.append(Btn(f"{page + 1}/{pages}", callback_data="dm_noop"))
    if page < pages - 1:
        nav.append(Btn("➡️", callback_data=f"dm_pg_{page + 1}"))
    rows.append(nav)
    if mode == "ex":
        rows.append([Btn("🔎 Via @username / ID", callback_data="dm_ex_id")])
        rows.append([Btn("✔️ Selesai", callback_data="dm_ex")])
        title = f"🛡 Pengecualian: {CATS[st['cat']]}"
        head = "Pilih kategori di atas, lalu tap chat untuk menambah / mencabut (🛡 = dikecualikan).\n"
    else:
        rows.append([Btn("⬅️ Kembali", callback_data="dm_menu")])
        title = f"📌 Pilih Chat: {CATS[st['cat']]}"
        head = "Pilih kategori di atas, lalu tap chat yang ingin dibersihkan.\n"
    body = (f"{_h(title)}{head}Atau ketik:\n"
            "• <b>nama chat</b> untuk mencari\n"
            "• <code>@username</code> / ID / link t.me\n\n"
            f"Ditemukan: <b>{len(items)}</b> chat")
    await _show(target, body, InlineKeyboardMarkup(rows))


async def _ask_range(target, uid: int):
    w = _st(uid)["wiz"]
    tgt = (f"{ICON[w['kind']]} <b>{_e(w['title'])}</b>" if w["scope"] == "one" else f"<b>{SCOPES[w['scope']]}</b>")
    kb = _rows([Btn(RANGES["today"], callback_data="dm_rng_today")],
               [Btn(RANGES["week"], callback_data="dm_rng_week")],
               [Btn(RANGES["all"], callback_data="dm_rng_all")],
               [Btn("⬅️ Kembali", callback_data="dm_menu")])
    await _show(target, f"{header_e('🕒', 'Rentang Waktu')}🎯 Target: {tgt}\n\nHapus pesan dari kapan?", kb)


async def _ask_mode(target, uid: int):
    body = ("🔁 <b>Dua arah</b>: hapus SEMUA pesan di chat pribadi (milikmu dan lawan bicara), "
            "hilang di kedua sisi.\n\n"
            "👤 <b>Hanya pesanku</b>: hanya pesan yang kamu kirim (ikut hilang di sisi lawan bicara).")
    kb = _rows([Btn(MODES["both"], callback_data="dm_mode_both")],
               [Btn(MODES["mine"], callback_data="dm_mode_mine")],
               [Btn("⬅️ Kembali", callback_data="dm_menu")])
    await _show(target, f"{header_e('🧹', 'Mode Hapus')}{body}", kb)


def _is_danger(w: dict) -> bool:
    return w["scope"] == "pm" and w["mode"] == "both" and w["range"] == "all"


async def _ask_confirm(target, uid: int):
    st = _st(uid)
    w = st["wiz"]
    cfg = get_userbot_settings(uid)
    tgt = f"{ICON[w['kind']]} {_e(w['title'])}" if w["scope"] == "one" else SCOPES[w["scope"]]
    body = (f"🎯 Target: <b>{tgt}</b>\n"
            f"🕒 Rentang: <b>{RANGES[w['range']]}</b>\n"
            f"🧹 Mode: <b>{MODES[w['mode']]}</b>\n"
            f"⚡ Kecepatan: <b>{SPEEDS[cfg['speed']][1]}</b>\n\n"
            "⚠️ Aksi ini <b>tidak bisa dibatalkan</b>.")
    ex_row = []
    if w["scope"] != "one":
        body += f"\n🛡 Pengecualian: <b>{len(cfg['exclude'])}</b> chat (tidak ikut dihapus)"
        ex_row = [[Btn("🛡 Atur pengecualian", callback_data="dm_ex")]]
    if _is_danger(w):
        delmsg_wait[uid] = "confirm_text"
        body += "\n\n🔴 Ini menghapus <b>SELURUH</b> chat pribadi dua arah.\nKetik <code>HAPUS</code> untuk melanjutkan."
        kb = InlineKeyboardMarkup(ex_row + [[Btn("❌ Batal", callback_data="dm_cancel")]])
    else:
        kb = InlineKeyboardMarkup([[Btn("✅ Mulai Hapus", callback_data="dm_go"),
                                    Btn("❌ Batal", callback_data="dm_cancel")]] + ex_row)
    await _show(target, f"{header_e('⚠️', 'Konfirmasi')}{body}", kb)


# ── Input teks (cari chat, @username/ID, channel tambahan, ketik HAPUS) ───────

async def handle_delmsg_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg, uid = update.effective_message, update.effective_user.id
    step = delmsg_wait.get(uid)
    text = (msg.text or "").strip()
    if not step:
        return
    if not text:
        await msg.reply_text("⚠️ Kirim dalam bentuk teks ya. Atau /cancel untuk batal.")
        return
    client = _client(uid)
    if not client:
        delmsg_wait.pop(uid, None)
        await msg.reply_text("❌ Session belum aktif. Lakukan /setup dulu.")
        return
    try:
        if step == "target":
            await _target_text(msg, uid, client, text)
        elif step == "addch":
            await _add_channels_text(msg, uid, client, text)
        elif step == "confirm_text":
            if text == "HAPUS":
                delmsg_wait.pop(uid, None)
                m = await msg.chat.send_message("⏳ Memulai...", reply_markup=_stop_kb())
                await _start_job(context.bot, uid, m.chat_id, m.message_id)
            else:
                delmsg_wait.pop(uid, None)
                await msg.reply_text("❎ Dibatalkan.")
                await del_menu(msg, uid)
    except Exception as e:
        traceback.print_exc()
        await msg.reply_text(f"❌ Error: {_e(e)}", parse_mode=ParseMode.HTML)


async def _target_text(msg: Message, uid: int, client, t: str):
    st = _st(uid)
    cfg = get_userbot_settings(uid)
    if re.fullmatch(r"-?\d+", t) or t.startswith("@") or "t.me/" in t:
        ref = t
        if "t.me/" in t:
            ref = "@" + t.split("t.me/")[-1].split("/")[0].split("?")[0]
        elif re.fullmatch(r"-?\d+", t):
            ref = int(t)
        try:
            ent = await client.get_entity(ref)
        except Exception:
            await msg.reply_text("❌ Chat tidak ditemukan. Coba pilih dari daftar atau ketik nama chat.")
            return
        title = utils.get_display_name(ent) or str(t)
        if st["pick"] == "ex":
            kind = _kind_of(ent)
            cfg["exclude"][str(utils.get_peer_id(ent))] = {"t": title, "k": kind}
            save_userbot_settings(uid, cfg)
            await msg.chat.send_message(f"🛡 {ICON[kind]} <b>{_e(title)}</b> ditambahkan ke pengecualian ({CATS[kind]}).",
                                        parse_mode=ParseMode.HTML)
            await _ex_menu(msg, uid)
            return
        st["wiz"].update(target=ent, title=title, kind=_kind_of(ent))
        delmsg_wait.pop(uid, None)
        await _ask_range(msg, uid)
        return
    q = t.lower()
    items = [x for x in st["dlgs"] if q in x[1].lower()]
    if not items:
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", t):
            await _target_text(msg, uid, client, "@" + t)          # coba sebagai username
            return
        await msg.reply_text("🔍 Tidak ada chat dengan nama itu. Coba kata lain, atau kirim @username / ID.")
        return
    await _show_picker(msg, uid, items, 0)


# ── Pengecualian ──────────────────────────────────────────────────────────────

async def _ex_menu(target, uid: int):
    st = _st(uid)
    delmsg_wait.pop(uid, None)
    st["pick"] = "del"
    cfg = get_userbot_settings(uid)
    excl = cfg["exclude"]
    groups = {"group": [], "channel": [], "pm": [], "other": []}
    for v in excl.values():
        t = v["t"] if isinstance(v, dict) else str(v)
        k = v.get("k") if isinstance(v, dict) else None
        groups[k if k in CATS else "other"].append(t)
    lines = []
    for k, lbl in list(CATS.items()) + [("other", "📁 Lainnya")]:
        names = groups[k]
        if not names:
            continue
        lines.append(f"\n<b>{lbl} ({len(names)})</b>")
        lines += [f"• {_e(t)}" for t in names[:10]]
        if len(names) > 10:
            lines.append(f"… +{len(names) - 10} lainnya")
    listing = "\n".join(lines) if lines else "\n<i>Belum ada.</i>"
    body = ("Chat di daftar ini <b>tidak akan dihapus</b> oleh mode massal (grup, channel, pribadi, komentar). "
            "Jika channel dikecualikan, grup diskusinya ikut aman.\n"
            "<i>Kalau kamu memilih '1 chat tertentu', pilihanmu tetap dijalankan.</i>\n\n"
            f"🛡 Total dikecualikan: <b>{len(excl)}</b>{listing}")
    kb = _rows([Btn("➕ Tambah / cabut (per kategori)", callback_data="dm_ex_add")],
               [Btn("🔎 Tambah via @username / ID", callback_data="dm_ex_id")],
               [Btn("🧹 Kosongkan", callback_data="dm_ex_clear")],
               [Btn("⬅️ Kembali", callback_data="dm_ex_back")])
    await _show(target, f"{header_e('🛡', 'Pengecualian')}{body}", kb)


# ── Komentar channel ──────────────────────────────────────────────────────────

async def _cm_menu(target, uid: int):
    st = _st(uid)
    delmsg_wait.pop(uid, None)
    st["wiz"] = {}
    extra = get_userbot_settings(uid)["extra"]
    lines = "\n".join(f"• {_e(x['title'])}" for x in extra[:15]) or "<i>Belum ada.</i>"
    if len(extra) > 15:
        lines += f"\n… dan {len(extra) - 15} lainnya"
    body = ("Komentar di channel tersimpan di <b>grup diskusi</b>-nya, walau kamu tidak join grupnya.\n\n"
            "Telegram tidak punya daftar semua tempat kamu pernah komentar, jadi bot memindai:\n"
            "1️⃣ channel yang kamu ikuti\n"
            "2️⃣ channel yang pernah kamu tinggalkan\n"
            "3️⃣ channel tambahan dari daftarmu (kalau kamu komentar di channel yang tidak diikuti, tambahkan di sini)\n\n"
            f"➕ Channel tambahan: <b>{len(extra)}</b>\n{lines}")
    kb = _rows([Btn("▶️ Mulai hapus komentar", callback_data="dm_scope_comments")],
               [Btn("➕ Tambah channel", callback_data="dm_cm_add"), Btn("🧹 Kosongkan", callback_data="dm_cm_clear")],
               [Btn("⬅️ Kembali", callback_data="dm_menu")])
    await _show(target, f"{header_e('💭', 'Komentar Channel')}{body}", kb)


async def _add_channels_text(msg: Message, uid: int, client, text: str):
    cfg = get_userbot_settings(uid)
    extra = cfg["extra"]
    added, failed = 0, []
    for tok in re.split(r"[\s,]+", text.strip()):
        if not tok:
            continue
        m = re.search(r"t\.me/c/(\d+)", tok)
        if m:
            ref = int("-100" + m.group(1))
        elif "t.me/" in tok:
            ref = "@" + tok.split("t.me/")[-1].split("/")[0].split("?")[0]
        elif re.fullmatch(r"-?\d+", tok):
            ref = int(tok)
        else:
            ref = tok
        try:
            ent = await client.get_entity(ref)
        except Exception:
            failed.append(tok)
            continue
        if _kind_of(ent) != "channel":
            failed.append(tok + " (bukan channel)")
            continue
        cid = utils.get_peer_id(ent)
        if any(x["id"] == cid for x in extra):
            continue
        extra.append({"id": cid, "ref": ent.username or cid, "title": utils.get_display_name(ent)})
        added += 1
    save_userbot_settings(uid, cfg)
    note = f"✅ Ditambahkan: <b>{added}</b> channel."
    if failed:
        note += "\n⚠️ Gagal: " + ", ".join(f"<code>{_e(x)}</code>" for x in failed[:10])
    await msg.chat.send_message(note, parse_mode=ParseMode.HTML)
    await _cm_menu(msg, uid)


async def _linked_group(client, ch):
    for _ in range(3):
        try:
            full = await client(GetFullChannelRequest(ch))
            lid = getattr(full.full_chat, "linked_chat_id", None)
            if not lid:
                return None
            for c in full.chats:
                if c.id == lid:
                    return c
            return None
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
        except Exception:
            return None
    return None


async def _collect_comment_groups(client, cfg, joined, seen, job):
    excl = cfg["exclude"]
    sources = {}
    for c in joined:
        sources[utils.get_peer_id(c)] = c
    try:  # channel yang pernah ditinggalkan
        off = 0
        for _ in range(10):
            res = await client(GetLeftChannelsRequest(offset=off))
            chats = getattr(res, "chats", [])
            if not chats:
                break
            for c in chats:
                if isinstance(c, Channel) and c.broadcast and not c.megagroup:
                    sources.setdefault(utils.get_peer_id(c), c)
            off += len(chats)
    except Exception:
        pass
    for x in cfg["extra"]:  # channel tambahan manual
        try:
            c = await client.get_entity(x["ref"])
            sources.setdefault(utils.get_peer_id(c), c)
        except Exception:
            pass
    out, n = [], len(sources)
    for i, (cid, ch) in enumerate(sources.items(), 1):
        if job:
            if job.stop.is_set():
                break
            job.cur = f"Memindai channel {i}/{n}"
        if str(cid) in excl:
            continue
        g = await _linked_group(client, ch)
        await asyncio.sleep(0.3)
        if not g:
            continue
        gid = utils.get_peer_id(g)
        if gid in seen or str(gid) in excl:
            continue
        seen.add(gid)
        out.append((g, "group", f"💭 {utils.get_display_name(g)}"))
    return out


# ── Penghapusan ───────────────────────────────────────────────────────────────

async def _collect_targets(client, cfg, w, job=None):
    scope = w["scope"]
    if scope == "one":
        return [(w["target"], w["kind"], w["title"])]
    excl = cfg["exclude"]
    out, seen, chans = [], set(), []
    async for d in client.iter_dialogs():
        ent = d.entity
        k = _kind_of(ent)
        if getattr(ent, "is_self", False) or d.id == 777000:
            continue
        pid = utils.get_peer_id(ent)
        if k == "channel":
            chans.append(ent)
        if str(pid) in excl:
            continue
        if (scope in ("groups", "groupsall") and k == "group") or \
           (scope == "channels" and k == "channel") or \
           (scope == "pm" and k == "pm"):
            out.append((ent, k, utils.get_display_name(ent) or str(d.id)))
            seen.add(pid)
    if scope in ("comments", "groupsall"):
        out += await _collect_comment_groups(client, cfg, chans, seen, job)
    return out


async def _purge_one(client, cfg, ent, kind, cutoff, mode, job):
    kw = {}
    filt_out = False
    if kind == "group":
        kw["from_user"] = "me"      # pencarian di server: cepat walau ribuan pesan
    elif kind == "pm":
        filt_out = (mode == "mine")
    else:
        filt_out = True             # channel: pilih postingan sendiri
    delay = SPEEDS[cfg["speed"]][0]
    batch = []

    async def flush():
        nonlocal batch
        if not batch:
            return True
        ids, batch = batch, []
        while True:
            try:
                await client.delete_messages(ent, ids, revoke=True)
                job.deleted += len(ids)
                break
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 1)
            except Exception:
                job.errors += len(ids)
                return False
        await asyncio.sleep(delay)
        return True

    async for m in client.iter_messages(ent, **kw):
        if job.stop.is_set():
            break
        job.scanned += 1
        if cutoff and m.date and m.date < cutoff:
            break
        if getattr(m, "action", None):
            continue
        if filt_out and not m.out:
            continue
        batch.append(m.id)
        if len(batch) >= 100:
            if not await flush():
                return
    await flush()


def _stop_kb() -> InlineKeyboardMarkup:
    return _rows([Btn("⛔ Hentikan", callback_data="dm_stop")])


def _prog_text(job: Job) -> str:
    filled = int(10 * max(job.idx - 1, 0) / job.total) if job.total else 0
    bar = "█" * filled + "░" * (10 - filled)
    return (f"{header_e('⏳', 'Sedang Menghapus...')}"
            f"🎯 Chat: <b>{_e(job.cur)}</b> ({job.idx}/{job.total})\n"
            f"[{bar}]\n"
            f"🔎 Terpindai: <b>{job.scanned}</b>\n"
            f"🗑 Terhapus: <b>{job.deleted}</b>\n"
            f"⚠️ Gagal: <b>{job.errors}</b>\n"
            f"⏱ {_fmt_t(time.time() - job.t0)}")


async def _ticker(bot, job: Job, chat_id: int, msg_id: int):
    while not job.done:
        await asyncio.sleep(3)
        try:
            await bot.edit_message_text(_prog_text(job), chat_id=chat_id, message_id=msg_id,
                                        reply_markup=_stop_kb(), parse_mode=ParseMode.HTML)
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception:
            pass


async def _run_job(bot, uid: int, chat_id: int, msg_id: int, client, cfg: dict, w: dict, job: Job):
    tick = asyncio.create_task(_ticker(bot, job, chat_id, msg_id))
    err = None
    try:
        targets = await _collect_targets(client, cfg, w, job)
        job.total = len(targets)
        cutoff = _cutoff_for(w["range"])
        for i, (ent, kind, title) in enumerate(targets, 1):
            if job.stop.is_set():
                break
            job.idx, job.cur = i, title
            try:
                await _purge_one(client, cfg, ent, kind, cutoff, w["mode"], job)
            except Exception:
                job.errors += 1
    except Exception as e:
        err = e
        traceback.print_exc()
    finally:
        job.done = True
        tick.cancel()
    title = "⛔ Dihentikan" if job.stop.is_set() else ("❌ Terjadi Error" if err else "✅ Selesai")
    body = (f"💬 Chat diproses: <b>{job.idx}/{job.total}</b>\n"
            f"🔎 Terpindai: <b>{job.scanned}</b>\n"
            f"🗑 Terhapus: <b>{job.deleted}</b> <i>(perkiraan)</i>\n"
            f"⚠️ Gagal: <b>{job.errors}</b>\n"
            f"⏱ Durasi: {_fmt_t(time.time() - job.t0)}")
    if job.total == 0 and not err:
        body = "Tidak ada chat yang cocok dengan pilihanmu."
    if err:
        body += f"\n\n<code>{_e(err)}</code>"
    kb = _rows([Btn("🗑 Hapus lagi", callback_data="dm_menu")], [_BACK_FITUR])
    text = f"{_h(title)}{body}"
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=kb,
                                    parse_mode=ParseMode.HTML)
    except Exception:
        try:
            await bot.send_message(chat_id, text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _start_job(bot, uid: int, chat_id: int, msg_id: int):
    st = _st(uid)
    job = st["job"]
    if job and not job.done:
        await bot.send_message(chat_id, "⏳ Masih ada proses yang berjalan. Tunggu atau hentikan dulu.")
        return
    client = _client(uid)
    if not client:
        await bot.send_message(chat_id, "❌ Session belum aktif. Lakukan /setup dulu.")
        return
    w = dict(st["wiz"])
    cfg = get_userbot_settings(uid)
    job = Job()
    st["job"] = job
    delmsg_wait.pop(uid, None)
    job.task = asyncio.create_task(_run_job(bot, uid, chat_id, msg_id, client, cfg, w, job))


# ── Router callback ───────────────────────────────────────────────────────────

async def delmsg_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    d = query.data
    uid = query.from_user.id
    if d == "dm_noop":
        await query.answer()
        return
    st = _st(uid)

    if d == "dm_stop":
        job = st["job"]
        if job and not job.done:
            job.stop.set()
            await query.answer("⛔ Menghentikan...", show_alert=True)
        else:
            await query.answer("Tidak ada proses berjalan")
        return

    client = _client(uid)
    if not client:
        await query.answer()
        await edit_or_send(query, "❌ Session belum aktif. Lakukan /setup dulu.", back_to_fitur_keyboard())
        return

    try:
        await _route(query, context, uid, st, client, d)
    except KeyError:
        # tombol lama setelah bot restart: state wizard sudah hilang
        await query.answer("Sesi menu kedaluwarsa, mulai lagi ya.", show_alert=True)
        await del_menu(query, uid)
        return
    except Exception as e:
        traceback.print_exc()
        try:
            await query.answer(f"Error: {e}"[:190], show_alert=True)
        except Exception:
            pass
        return
    try:
        await query.answer()
    except Exception:
        pass


async def _route(query, context, uid: int, st: dict, client, d: str):
    cfg = get_userbot_settings(uid)
    if d in ("fitur_delmsg", "dm_menu"):
        await del_menu(query, uid)
    elif d == "dm_speed":
        order = list(SPEEDS)
        cfg["speed"] = order[(order.index(cfg["speed"]) + 1) % len(order)]
        save_userbot_settings(uid, cfg)
        await del_menu(query, uid)
    elif d == "dm_ex":
        await _ex_menu(query, uid)
    elif d == "dm_ex_add":
        st["pick"], st["cat"] = "ex", "group"
        await query.answer("⏳ Memuat daftar chat...")
        await _load_dialogs(client, st)
        delmsg_wait[uid] = "target"
        await _show_picker(query, uid, _cat_items(st), 0)
    elif d.startswith("dm_cat_"):
        st["cat"] = d[len("dm_cat_"):]
        delmsg_wait[uid] = "target"
        await _show_picker(query, uid, _cat_items(st), 0)
    elif d == "dm_ex_id":
        st["pick"] = "ex"
        delmsg_wait[uid] = "target"
        await _show(query, f"{header_e('🔎', 'Tambah via Username / ID')}"
                    "Kirim <code>@username</code>, ID angka, atau link <code>t.me/...</code> "
                    "dari chat yang mau dikecualikan.\n\n"
                    "Bisa untuk <b>chat pribadi</b>, grup, maupun channel.\n"
                    "<i>Untuk ID angka, akunmu harus pernah berinteraksi dengan chat/user itu; "
                    "kalau tidak ketemu, pakai @username.</i>",
                    _rows([Btn("⬅️ Kembali", callback_data="dm_ex")]))
    elif d == "dm_ex_clear":
        cfg["exclude"].clear()
        save_userbot_settings(uid, cfg)
        await _ex_menu(query, uid)
    elif d == "dm_ex_back":
        delmsg_wait.pop(uid, None)
        st["pick"] = "del"
        w = st["wiz"]
        if w.get("range") and w.get("mode"):
            await _ask_confirm(query, uid)
        else:
            await del_menu(query, uid)
    elif d == "dm_cm":
        await _cm_menu(query, uid)
    elif d == "dm_cm_add":
        delmsg_wait[uid] = "addch"
        await _show(query, f"{header_e('➕', 'Tambah Channel')}"
                    "Kirim <code>@username</code> atau link <code>t.me/namachannel</code> "
                    "channel tempat kamu pernah komentar.\n"
                    "Boleh banyak sekaligus, pisahkan dengan spasi atau baris baru.",
                    _rows([Btn("⬅️ Kembali", callback_data="dm_cm")]))
    elif d == "dm_cm_clear":
        cfg["extra"].clear()
        save_userbot_settings(uid, cfg)
        await _cm_menu(query, uid)
    elif d.startswith("dm_scope_"):
        scope = d[len("dm_scope_"):]
        if scope not in SCOPES:
            raise KeyError(scope)
        st["wiz"] = {"scope": scope}
        st["pick"] = "del"
        if scope == "one":
            await query.answer("⏳ Memuat daftar chat...")
            st["cat"] = "group"
            await _load_dialogs(client, st)
            delmsg_wait[uid] = "target"
            await _show_picker(query, uid, _cat_items(st), 0)
        else:
            await _ask_range(query, uid)
    elif d.startswith("dm_pg_"):
        await _show_picker(query, uid, st["view"], int(d[len("dm_pg_"):]))
    elif d.startswith("dm_pk_"):
        e, t, k = st["view"][int(d[len("dm_pk_"):])]
        if st["pick"] == "ex":
            pid = str(utils.get_peer_id(e))
            if pid in cfg["exclude"]:
                cfg["exclude"].pop(pid)
                await query.answer("Dicabut dari pengecualian")
            else:
                cfg["exclude"][pid] = {"t": t, "k": k}
                await query.answer("🛡 Dikecualikan")
            save_userbot_settings(uid, cfg)
            await _show_picker(query, uid, st["view"], st["page"])
        else:
            st["wiz"].update(target=e, title=t, kind=k)
            delmsg_wait.pop(uid, None)
            await _ask_range(query, uid)
    elif d.startswith("dm_rng_"):
        w = st["wiz"]
        w["scope"]                                        # KeyError bila state hilang
        w["range"] = d[len("dm_rng_"):]
        if w["scope"] == "pm" or (w["scope"] == "one" and w["kind"] == "pm"):
            await _ask_mode(query, uid)
        else:
            w["mode"] = "mine"
            await _ask_confirm(query, uid)
    elif d.startswith("dm_mode_"):
        st["wiz"]["scope"]
        st["wiz"]["mode"] = d[len("dm_mode_"):]
        await _ask_confirm(query, uid)
    elif d == "dm_cancel":
        delmsg_wait.pop(uid, None)
        st["wiz"] = {}
        await del_menu(query, uid)
    elif d == "dm_go":
        w = st["wiz"]
        if not (w.get("scope") and w.get("range") and w.get("mode")):
            raise KeyError("wiz")
        await _show(query, "⏳ Memulai...", _stop_kb())
        await _start_job(context.bot, uid, query.message.chat_id, query.message.message_id)
