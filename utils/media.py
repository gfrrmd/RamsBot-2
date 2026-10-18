import io

from telethon.tl.types import DocumentAttributeVideo, MessageMediaDocument, MessageMediaPhoto

from utils.helpers import get_file_name, get_video_attributes, is_sticker_doc
from utils.progress import make_upload_progress


async def _send_media_file(client, msg, media_bytes, status_msg, caption="", task_id=""):
    file_obj = io.BytesIO(media_bytes)
    up_cb = make_upload_progress(status_msg, task_id)

    if isinstance(msg.media, MessageMediaPhoto):
        file_obj.name = "photo.jpg"
        await client.send_file("me", file=file_obj, caption=caption, parse_mode="markdown", progress_callback=up_cb)
    elif isinstance(msg.media, MessageMediaDocument):
        doc = msg.media.document
        mime = getattr(doc, "mime_type", "") or ""
        if is_sticker_doc(doc):
            file_obj.name = "sticker.tgs" if "tgsticker" in mime else ("sticker.webm" if "video" in mime else "sticker.webp")
            await client.send_file("me", file=file_obj, force_document=False, progress_callback=up_cb)
        elif "video" in mime or "mp4" in mime:
            video_attr = get_video_attributes(doc)
            file_obj.name = get_file_name(doc) or "video.mp4"
            attrs = []
            if video_attr:
                attrs = [DocumentAttributeVideo(duration=video_attr.duration, w=video_attr.w, h=video_attr.h, supports_streaming=True, round_message=False)]
            await client.send_file("me", file=file_obj, caption=caption, parse_mode="markdown", attributes=attrs or None, allow_cache=False, progress_callback=up_cb)
        elif mime in ("image/jpeg", "image/png", "image/webp"):
            file_obj.name = "photo" + {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime, ".jpg")
            await client.send_file("me", file=file_obj, caption=caption, parse_mode="markdown", force_document=False, allow_cache=False, progress_callback=up_cb)
        else:
            fname = get_file_name(doc) or "document"
            if "." not in fname:
                fname += {"audio/mpeg": ".mp3", "audio/ogg": ".ogg", "application/pdf": ".pdf", "video/webm": ".webm", "image/gif": ".gif"}.get(mime, "")
            file_obj.name = fname
            await client.send_file("me", file=file_obj, caption=caption, parse_mode="markdown", force_document=False, allow_cache=False, progress_callback=up_cb)
    else:
        await client.send_file("me", file=file_obj, caption=caption, parse_mode="markdown", progress_callback=up_cb)
    try:
        await status_msg.delete()
    except Exception:
        pass


async def _send_story_file(client, story_media, media_bytes, status_msg, caption_text, task_id=""):
    wrapper = type("StoryWrapper", (), {"media": story_media})()
    await _send_media_file(client, wrapper, media_bytes, status_msg, caption_text, task_id)
