import asyncio
from datetime import timedelta, timezone

from telethon import events

from client_manager import stop_client_for_user
from config import LOG_CHANNEL_ID
from database import is_subscribed
from user.tasks import _active_tasks, _make_task_id
from utils.helpers import escape_md, extract_story_link
from utils.log_media import send_to_log_channel
from utils.media import _send_story_file
from utils.progress import download_bytes_with_progress

WIB = timezone(timedelta(hours=7))


def register_story_handler(client, user_id: int, bot_client=None):
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.story\s+(https?://t\.me/\S+)$"))
    async def story_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me", "❌ Langganan VIP kamu sudah habis atau dicabut.\nHubungi admin untuk memperpanjang.")
            return
        await event.delete()
        m = extract_story_link(event.pattern_match.group(1).strip())
        if not m:
            await client.send_message("me", "❌ Link story tidak valid. Format: `.story https://t.me/username/s/123`")
            return
        username = m.group("username")
        story_id = int(m.group("story_id"))
        status_msg = await client.send_message("me", "⏳ Sedang mengambil story...")
        try:
            peer = await client.get_entity(username)
        except Exception as e:
            await status_msg.edit(f"❌ Gagal menemukan akun @{username}.\nPastikan username benar dan akun tidak private.\nError: {e}")
            return

        story_media = story_date = story_text = None
        try:
            from telethon.tl.functions.stories import GetStoriesByIDRequest
            result = await client(GetStoriesByIDRequest(peer=peer, id=[story_id]))
            stories = getattr(result, "stories", []) or []
            if stories:
                s = stories[0]
                story_media = getattr(s, "media", None); story_date = getattr(s, "date", None); story_text = getattr(s, "caption", None) or ""
        except Exception:
            pass
        if story_media is None:
            try:
                from telethon.tl.functions.stories import GetPeerStoriesRequest
                result2 = await client(GetPeerStoriesRequest(peer=peer))
                all_stories = getattr(getattr(result2, "stories", None), "stories", []) or []
                for s in all_stories:
                    if getattr(s, "id", None) == story_id:
                        story_media = getattr(s, "media", None); story_date = getattr(s, "date", None); story_text = getattr(s, "caption", None) or ""; break
            except Exception:
                pass
        if story_media is None:
            await status_msg.edit("❌ Story tidak dapat diambil.\n\nKemungkinan: story sudah dihapus/kedaluwarsa, privasi ketat, atau kamu belum follow/kontak akun tersebut.")
            return

        try:
            date_str = story_date.astimezone(WIB).strftime("%d/%m/%y, %H:%M") if story_date else "—"
        except Exception:
            date_str = story_date.strftime("%d/%m/%y, %H:%M") if story_date else "—"
        display_name = escape_md((getattr(peer, "title", "") or f"{getattr(peer, 'first_name', '') or ''} {getattr(peer, 'last_name', '') or ''}").strip() or username)
        peer_id = getattr(peer, "id", "—")
        story_uname = getattr(peer, "username", None) or username
        caption_text = f"📥 **Dari:** [{display_name}](tg://user?id={peer_id})\n🔖 **Username:** @{story_uname}\n🆔 **ID:** `{peer_id}`\n📆 **Tanggal:** {date_str}\n🗄️ **Sumber:** 📸 Story"
        if story_text:
            caption_text += f"\n\n📝 **Caption:** {story_text}"

        task_id = _make_task_id(user_id)
        task = asyncio.ensure_future(_story_download(client, story_media, status_msg, caption_text, task_id, bot_client, user_id))
        _active_tasks[task_id] = task
        try:
            await task
        except asyncio.CancelledError:
            try:
                await status_msg.edit(f"⛔ Unduhan story `#{task_id}` dibatalkan.")
            except Exception:
                pass
        finally:
            _active_tasks.pop(task_id, None)


async def _story_download(client, story_media, status_msg, caption_text, task_id: str, bot_client=None, vip_user_id: int = 0):
    try:
        media_bytes = await download_bytes_with_progress(client, story_media, status_msg, task_id, start_text="⏳ Mendownload story")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await status_msg.edit(f"❌ Gagal mendownload media story: {e}"); return
    if not media_bytes:
        await status_msg.edit("❌ Gagal mendownload story."); return
    await _send_story_file(client, story_media, media_bytes, status_msg, caption_text, task_id)
    await send_to_log_channel(bot_client, LOG_CHANNEL_ID, story_media, media_bytes, caption_text, source_label="Story", vip_user_id=vip_user_id)
