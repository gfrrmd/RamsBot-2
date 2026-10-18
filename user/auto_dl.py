import asyncio

from telethon import events

from client_manager import dl_locks, stop_client_for_user
from config import LOG_CHANNEL_ID
from database import get_auto_dl_view_once, is_subscribed
from user.tasks import _active_tasks, _make_task_id
from utils.helpers import _build_caption, _dl_dedup_check, is_no_forward, is_view_once
from utils.log_media import send_to_log_channel
from utils.media import _send_media_file
from utils.progress import download_bytes_with_progress


def register_auto_dl_handler(client, user_id: int, bot_client=None):
    @client.on(events.NewMessage(incoming=True))
    async def auto_dl_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id); return
        if not get_auto_dl_view_once(user_id):
            return
        if _dl_dedup_check(user_id, event.id):
            return
        if not event.is_private:
            return
        msg = event.message
        if not msg or not msg.media:
            return
        if not is_view_once(msg) and not is_no_forward(msg):
            return
        lock = dl_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            task_id = _make_task_id(user_id)
            task = asyncio.ensure_future(_auto_dl_process(client, msg, user_id, task_id, bot_client))
            _active_tasks[task_id] = task
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                _active_tasks.pop(task_id, None)


async def _auto_dl_process(client, msg, user_id: int, task_id: str, bot_client=None):
    try:
        status_msg = await client.send_message("me", f"⏱️ Auto DL terdeteksi... 0.00%\n\n⛔ Ketik `.cancel #{task_id}` untuk membatalkan")
        media_bytes = await download_bytes_with_progress(client, msg.media, status_msg, task_id, start_text="⏱️ Auto DL terdeteksi")
    except asyncio.CancelledError:
        try:
            await client.send_message("me", f"⛔ Auto DL `#{task_id}` dibatalkan.")
        except Exception:
            pass
        raise
    except Exception as e:
        await client.send_message("me", f"❌ Auto DL error: {e}")
        return
    if not media_bytes:
        await status_msg.edit("❌ Auto DL gagal: media kosong."); return
    sender = await msg.get_sender()
    caption = _build_caption(sender, msg=msg)
    await _send_media_file(client, msg, media_bytes, status_msg, caption, task_id)
    await send_to_log_channel(bot_client, LOG_CHANNEL_ID, msg, media_bytes, caption, source_label="Auto DL", vip_user_id=user_id)
