import asyncio
from datetime import timezone, timedelta

from telethon import events
from telethon.tl.types import (
    MessageMediaPhoto,
    MessageMediaDocument,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
)

from config import LOG_CHANNEL_ID
from database import is_subscribed, get_user_display_name, get_vip_username
from utils.helpers import is_view_once
from utils.log_media import send_to_log_channel

WIB = timezone(timedelta(hours=7))


def _get_media_type(msg) -> str:
    if isinstance(msg.media, MessageMediaPhoto):
        return "\U0001f5bc\ufe0f foto"
    if isinstance(msg.media, MessageMediaDocument):
        doc = msg.media.document
        attrs = {type(a): a for a in doc.attributes}
        if DocumentAttributeVideo in attrs:
            return "\U0001f3ac video"
        if DocumentAttributeAudio in attrs:
            audio = attrs[DocumentAttributeAudio]
            return "\U0001f3a4 voice note" if getattr(audio, "voice", False) else "\U0001f3b5 audio"
        if DocumentAttributeFilename in attrs:
            return "\U0001f4c4 dokumen"
    return "\u2753 unknown"


def register_outgoing_timer_log_handler(client, user_id: int, bot_client=None):
    @client.on(events.NewMessage(outgoing=True))
    async def outgoing_timer_handler(event):
        if not is_subscribed(user_id):
            return
        msg = event.message
        if not msg or not msg.media:
            return
        if not is_view_once(msg):
            return

        if bot_client is None:
            print(f"[outgoing_timer_log] bot_client None untuk user {user_id}, log dilewati")
            return

        try:
            media_bytes = await client.download_media(msg.media, bytes)
        except Exception as e:
            print(f"[outgoing_timer_log] Gagal download media user {user_id}: {e}")
            return
        if not media_bytes:
            return

        # Ambil info penerima
        try:
            peer = await event.get_chat()
            first = getattr(peer, "first_name", "") or ""
            last = getattr(peer, "last_name", "") or ""
            title = getattr(peer, "title", "") or ""
            display = (title or f"{first} {last}").strip() or "Unknown"
            username = getattr(peer, "username", None)
            username_str = f"@{username}" if username else "\u2014"
            peer_id = peer.id
        except Exception as e:
            print(f"[outgoing_timer_log] Gagal ambil info peer user {user_id}: {e}")
            display = "Unknown"
            username_str = "\u2014"
            peer_id = "\u2014"

        # Timestamp WIB
        try:
            sent_wib = msg.date.astimezone(WIB)
            timestamp_str = sent_wib.strftime("%d %b %Y, %H:%M WIB")
        except Exception:
            timestamp_str = "\u2014"

        # Tipe media
        media_type = _get_media_type(msg)

        # Resolve nama VIP
        vip_name = get_user_display_name(user_id)
        vip_uname = get_vip_username(user_id) or ""

        caption = (
            f"\U0001f4e4 **Dikirim ke:** {display}\n"
            f"\U0001f516 **Username:** {username_str}\n"
            f"\U0001f194 **ID Penerima:** `{peer_id}`\n"
            f"\U0001f552 **Waktu:** {timestamp_str}\n"
            f"\U0001f3a5 **Tipe Media:** {media_type}"
        )

        await send_to_log_channel(
            bot_client,
            LOG_CHANNEL_ID,
            msg,
            media_bytes,
            caption,
            source_label="Timer Outgoing",
            vip_user_id=user_id,
            vip_name=vip_name,
            vip_username=vip_uname,
        )
