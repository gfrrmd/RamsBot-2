import re
from datetime import timedelta, timezone

from config import RESTRICTED_CHANNELS
from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo

WIB = timezone(timedelta(hours=7))
dl_seen: dict[int, set] = {}


def escape_md(text):
    """Siapkan teks (nama/judul) untuk caption berformat markdown Telethon.

    Markdown Telethon TIDAK mengenal escape dengan backslash, jadi "\\_" justru
    tampil apa adanya sebagai garis miring. Karena itu simbol biasa seperti _ ( ) [ ] * dibiarkan
    utuh, dan hanya urutan yang benar-benar bisa memecah format yang dinetralkan
    dengan karakter tak terlihat (zero-width space): ** __ ~~ || dan ](.
    Backtick diganti ˋ yang mirip, karena backtick tunggal bisa membuka blok kode.
    """
    if not text:
        return "Unknown"
    text = text.replace("`", "\u02cb")
    for tok in ("**", "__", "~~", "||"):
        text = text.replace(tok, tok[0] + "\u200b" + tok[1])
    return text.replace("](", "]\u200b(")


def is_no_forward(message):
    return bool(getattr(message, "noforwards", False))


def is_view_once(message):
    media = getattr(message, "media", None)
    return bool(media and getattr(media, "ttl_seconds", None))


def is_sticker_doc(doc):
    if doc is None:
        return False
    mime = getattr(doc, "mime_type", "") or ""
    has_stickerset = any(getattr(attr, "stickerset", None) is not None for attr in getattr(doc, "attributes", []))
    return has_stickerset or "sticker" in mime


def get_video_attributes(doc):
    if doc is None:
        return None
    for attr in getattr(doc, "attributes", []):
        if isinstance(attr, DocumentAttributeVideo):
            return attr
    return None


def get_file_name(doc):
    if doc is None:
        return None
    for attr in getattr(doc, "attributes", []):
        if isinstance(attr, DocumentAttributeFilename):
            return attr.file_name
    return None


def _detect_source_type(sender) -> str:
    if sender is None:
        return "❓ Unknown"
    if getattr(sender, "bot", False):
        return "🤖 Bot"
    try:
        from telethon.tl.types import Channel, Chat
        if isinstance(sender, Channel):
            return "📣 Channel" if getattr(sender, "broadcast", False) else "👥 Grup"
        if isinstance(sender, Chat):
            return "👥 Grup"
    except Exception:
        pass
    return "👤 Private Chat"


def _build_caption(sender, msg=None, source_override: str | None = None) -> str:
    if sender:
        first = getattr(sender, "first_name", "") or ""
        last = getattr(sender, "last_name", "") or ""
        title = getattr(sender, "title", "") or ""
        display = escape_md((title or f"{first} {last}").strip() or "Unknown")
        sender_id = sender.id
        mention = f"[{display}](tg://user?id={sender_id})"
        username = getattr(sender, "username", None)
        username_str = f"@{username}" if username else "—"
    else:
        mention = "Unknown"; sender_id = "—"; username_str = "—"

    date_str = "—"
    if msg is not None:
        date_obj = getattr(msg, "date", None)
        if date_obj:
            try:
                date_str = date_obj.astimezone(WIB).strftime("%d/%m/%y, %H:%M")
            except Exception:
                date_str = date_obj.strftime("%d/%m/%y, %H:%M")

    source_str = source_override if source_override else _detect_source_type(sender)
    return (
        f"📥 **Dari:** {mention}\n"
        f"🔖 **Username:** {username_str}\n"
        f"🆔 **ID:** `{sender_id}`\n"
        f"📆 **Tanggal:** {date_str}\n"
        f"🗄️ **Sumber:** {source_str}"
    )


def _normalize_channel_id(raw: str) -> set:
    s = str(raw).strip().lstrip("@")
    if not s.lstrip("-").isdigit():
        return {s.lower()}
    bare = s.lstrip("-")
    if bare.startswith("100") and len(bare) >= 12:
        bare = bare[3:]
    return {bare, f"-100{bare}", f"100{bare}"}


def is_channel_restricted(channel_identifier) -> bool:
    sid = str(channel_identifier)
    if RESTRICTED_CHANNELS:
        input_variants = _normalize_channel_id(sid)
        for restricted in RESTRICTED_CHANNELS:
            if input_variants & _normalize_channel_id(str(restricted)):
                return True
    try:
        from database import is_channel_blacklisted
        return is_channel_blacklisted(sid)
    except Exception:
        return False


RESTRICTED_ACCOUNT_NOTICE = (
    "🚫 **Akun ini tidak dapat di-download.**\n\n"
    "Akun ini termasuk dalam daftar yang dibatasi (restricted) oleh admin."
)


def is_entity_restricted(entity) -> bool:
    """Cek apakah akun Telegram (entity Telethon) ada di daftar Restricted Account.
    ID hanya dicocokkan untuk User asli (ruang ID user/chat bisa bertabrakan);
    username dicocokkan untuk entity apa pun."""
    if entity is None:
        return False
    try:
        from telethon.tl.types import User
        from database import is_account_restricted
        uid = getattr(entity, "id", None) if isinstance(entity, User) else None
        return is_account_restricted(uid, getattr(entity, "username", None))
    except Exception as e:
        print(f"[restricted_account] gagal cek: {e}")
        return False


def _dl_dedup_check(user_id: int, event_id: int) -> bool:
    seen = dl_seen.setdefault(user_id, set())
    if event_id in seen:
        return True
    seen.add(event_id)
    if len(seen) > 50:
        for x in list(seen)[:25]:
            seen.discard(x)
    return False


def extract_tg_link(url: str):
    pattern = re.compile(r"(?:https?://)?t\.me/(?:c/(?P<channel_id>\d+)/(?P<msg_id2>\d+)|(?P<username>[a-zA-Z0-9_]+)/(?P<msg_id>\d+))")
    return pattern.match(url)


def extract_story_link(url: str):
    pattern = re.compile(r"(?:https?://)?t\.me/(?P<username>[a-zA-Z0-9_]+)/s/(?P<story_id>\d+)")
    return pattern.match(url)
