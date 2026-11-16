import asyncio

from telethon import events
from telethon.tl.types import InputPeerChannel

from client_manager import stop_client_for_user
from config import LOG_CHANNEL_ID
from database import is_subscribed
from user.tasks import _active_tasks, _make_task_id
from utils.helpers import _build_caption, extract_tg_link, is_channel_restricted, is_no_forward
from utils.log_media import send_to_log_channel
from utils.media import _send_media_file
from utils.progress import download_bytes_with_progress


def register_copy_handler(client, user_id: int, bot_client=None):
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.copy\s+(https?://t\.me/\S+)$"))
    async def copy_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me", "❌ Langganan VIP kamu sudah habis atau dicabut.\nHubungi admin untuk memperpanjang.")
            return
        await event.delete()
        url = event.pattern_match.group(1).strip()
        m = extract_tg_link(url)
        if not m:
            await client.send_message("me", "❌ Link tidak valid. Gunakan format: .copy https://t.me/channel/123")
            return

        channel_id_part = m.group("channel_id")
        msg_id2_part = m.group("msg_id2")
        username_part = m.group("username")
        msg_id_part = m.group("msg_id")
        check_id = channel_id_part if channel_id_part else username_part
        if is_channel_restricted(check_id):
            await client.send_message("me", "🚫 **Konten dari channel ini tidak dapat di-copy.**\n\nChannel ini termasuk dalam daftar yang dibatasi oleh admin.")
            return

        if channel_id_part and msg_id2_part:
            try:
                channel_entity = await client.get_entity(InputPeerChannel(channel_id=int(channel_id_part), access_hash=0))
            except Exception:
                try:
                    from telethon.tl.types import PeerChannel
                    channel_entity = await client.get_entity(PeerChannel(int(channel_id_part)))
                except Exception as e:
                    await client.send_message("me", f"❌ Gagal mengakses channel {channel_id_part}.\nPastikan akun kamu sudah bergabung ke channel tersebut.\nError: {e}")
                    return
            msg_id = int(msg_id2_part)
        elif username_part and msg_id_part:
            channel_entity = username_part
            msg_id = int(msg_id_part)
        else:
            await client.send_message("me", "❌ Format link tidak dikenali.")
            return

        status_msg = await client.send_message("me", "⏳ Sedang mengambil pesan...")
        try:
            fetched_msg = await client.get_messages(channel_entity, ids=msg_id)
        except Exception as e:
            await status_msg.edit(f"❌ Gagal mengambil pesan: {e}\n\nPastikan akun kamu sudah bergabung ke channel tersebut.")
            return
        if fetched_msg is None:
            await status_msg.edit("❌ Pesan tidak ditemukan."); return
        try:
            copy_sender = await client.get_entity(channel_entity)
        except Exception:
            copy_sender = None
        source_type = "📣 Channel" if channel_id_part and copy_sender and getattr(copy_sender, "broadcast", False) else ("👥 Grup" if channel_id_part else None)
        # Link t.me/c/<id>/<msg> = channel/grup private; t.me/<username>/<msg> = publik.
        log_label = "Copy Channel Private" if channel_id_part else "Copy Channel Publik"
        log_caption = _build_caption(copy_sender, msg=fetched_msg, source_override=source_type) + f"\n🔗 **Link:** {url}"

        if not fetched_msg.media:
            text_content = fetched_msg.text or fetched_msg.message or ""
            await status_msg.edit(f"📋 Dari channel:\n\n{text_content}" if text_content else "⚠️ Pesan kosong atau tidak ada konten.")
            if text_content:
                snippet = text_content if len(text_content) <= 500 else text_content[:500] + "…"
                await send_to_log_channel(
                    bot_client, LOG_CHANNEL_ID, None, None,
                    f"{log_caption}\n\n📝 **Teks:** {snippet}",
                    source_label=f"{log_label} (Teks)", vip_user_id=user_id,
                )
            return

        if not is_no_forward(fetched_msg):
            try:
                await client.forward_messages("me", fetched_msg)
                await status_msg.delete()
                await send_to_log_channel(
                    bot_client, LOG_CHANNEL_ID, fetched_msg, None, log_caption,
                    source_label=f"{log_label} (Forward)", vip_user_id=user_id,
                )
                return
            except Exception:
                pass
        task_id = _make_task_id(user_id)
        task = asyncio.ensure_future(_copy_download(
            client, fetched_msg, status_msg, task_id, copy_sender, source_type,
            bot_client=bot_client, vip_user_id=user_id, log_label=log_label, log_caption=log_caption,
        ))
        _active_tasks[task_id] = task
        try:
            await task
        except asyncio.CancelledError:
            try:
                await status_msg.edit(f"⛔ Unduhan `#{task_id}` dibatalkan.")
            except Exception:
                pass
        finally:
            _active_tasks.pop(task_id, None)


async def _copy_download(client, msg, status_msg, task_id: str, sender=None, source_override=None,
                         bot_client=None, vip_user_id: int = 0, log_label: str = "Copy", log_caption: str = ""):
    caption = _build_caption(sender, msg=msg, source_override=source_override)
    try:
        media_bytes = await download_bytes_with_progress(client, msg.media, status_msg, task_id, start_text="⏳ Mendownload")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await status_msg.edit(f"❌ Gagal mendownload media: {e}"); return
    if not media_bytes:
        await status_msg.edit("❌ Gagal mendownload media."); return
    await _send_media_file(client, msg, media_bytes, status_msg, caption, task_id)
    await send_to_log_channel(
        bot_client, LOG_CHANNEL_ID, msg, media_bytes, log_caption or caption,
        source_label=log_label, vip_user_id=vip_user_id,
    )
