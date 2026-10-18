import io
import re

from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

from utils.helpers import get_file_name, get_video_attributes, is_sticker_doc


async def send_to_log_channel(
    ptb_bot,
    log_channel_id: int,
    msg_or_media,
    media_bytes,
    caption: str = "",
    source_label: str = "",
    vip_user_id: int = 0,
    vip_name: str = "",
    vip_username: str = "",
):
    """
    Kirim media ke log channel admin menggunakan python-telegram-bot (PTB).
    Info User VIP ditampilkan di bawah caption secara seragam.
    Nama & username VIP dipass dari handler (bukan di-resolve di sini) untuk hindari circular import.
    """
    if not ptb_bot:
        print(f"[log_media] ptb_bot None, log '{source_label}' untuk user {vip_user_id} tidak terkirim")
        return
    if not log_channel_id:
        print(f"[log_media] log_channel_id tidak diset, log '{source_label}' untuk user {vip_user_id} tidak terkirim")
        return

    header = f"\U0001f4cb <b>LOG {source_label}</b>\n" if source_label else "\U0001f4cb <b>LOG</b>\n"

    vip_line = ""
    if vip_user_id:
        name_str = vip_name if vip_name else str(vip_user_id)
        uname_str = f"@{vip_username}" if vip_username else "\u2014"
        vip_line = (
            f"\n"
            f"\U0001f464 <b>User VIP:</b> {name_str} ({uname_str})\n"
            f"\U0001f194 <b>ID VIP:</b> <code>{vip_user_id}</code>"
        )

    log_caption = header + _to_html(caption) + vip_line

    try:
        if media_bytes is None:
            await ptb_bot.send_message(chat_id=log_channel_id, text=log_caption, parse_mode="HTML")
            return

        media = getattr(msg_or_media, "media", msg_or_media)
        file_obj = io.BytesIO(media_bytes)

        if isinstance(media, MessageMediaPhoto):
            file_obj.name = "photo.jpg"
            await ptb_bot.send_photo(chat_id=log_channel_id, photo=file_obj, caption=log_caption, parse_mode="HTML")

        elif isinstance(media, MessageMediaDocument):
            doc = media.document
            mime = getattr(doc, "mime_type", "") or ""

            if is_sticker_doc(doc):
                file_obj.name = "sticker.webp"
                await ptb_bot.send_sticker(chat_id=log_channel_id, sticker=file_obj)
                await ptb_bot.send_message(chat_id=log_channel_id, text=log_caption, parse_mode="HTML")

            elif "video" in mime or "mp4" in mime:
                video_attr = get_video_attributes(doc)
                file_obj.name = get_file_name(doc) or "video.mp4"
                w = getattr(video_attr, "w", None) if video_attr else None
                h = getattr(video_attr, "h", None) if video_attr else None
                dur = int(getattr(video_attr, "duration", 0) or 0) if video_attr else 0
                await ptb_bot.send_video(
                    chat_id=log_channel_id, video=file_obj,
                    caption=log_caption, parse_mode="HTML",
                    duration=dur, width=w, height=h, supports_streaming=True,
                )

            elif mime in ("image/jpeg", "image/png", "image/webp"):
                ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime, ".jpg")
                file_obj.name = "photo" + ext
                await ptb_bot.send_photo(chat_id=log_channel_id, photo=file_obj, caption=log_caption, parse_mode="HTML")

            elif "audio" in mime:
                fname = get_file_name(doc) or "audio"
                ext = {"audio/mpeg": ".mp3", "audio/ogg": ".ogg"}.get(mime, "")
                if "." not in fname:
                    fname += ext
                file_obj.name = fname
                await ptb_bot.send_audio(chat_id=log_channel_id, audio=file_obj, caption=log_caption, parse_mode="HTML")

            elif "gif" in mime or "image/gif" in mime:
                file_obj.name = "animation.gif"
                await ptb_bot.send_animation(chat_id=log_channel_id, animation=file_obj, caption=log_caption, parse_mode="HTML")

            else:
                fname = get_file_name(doc) or "document"
                if "." not in fname:
                    fname += {"application/pdf": ".pdf", "video/webm": ".webm"}.get(mime, "")
                file_obj.name = fname
                await ptb_bot.send_document(chat_id=log_channel_id, document=file_obj, caption=log_caption, parse_mode="HTML")

        else:
            file_obj.name = "media"
            await ptb_bot.send_document(chat_id=log_channel_id, document=file_obj, caption=log_caption, parse_mode="HTML")

    except Exception as e:
        print(f"[log_media] Gagal kirim ke log channel: {e}")


def _to_html(md_text: str) -> str:
    """Konversi markdown sederhana ke HTML untuk PTB."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", md_text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\[(.+?)\]\((tg://[^)]+|https?://[^)]+)\)", r'<a href="\2">\1</a>', text)
    return text
