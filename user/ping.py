import time

from telethon import events

from client_manager import _start_time, stop_client_for_user
from database import is_subscribed
from user.tasks import register_cancel_task_handler


def register_ping_handler(client, user_id: int):
    register_cancel_task_handler(client)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.ping$"))
    async def ping_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id)
            await event.client.send_message("me", "❌ Langganan VIP kamu sudah habis atau dicabut.\nHubungi admin untuk memperpanjang.")
            return
        start = time.monotonic()
        msg = await event.edit("🏓 Pinging...")
        ping_ms = (time.monotonic() - start) * 1000
        uptime = int(time.monotonic() - _start_time.get(user_id, time.monotonic()))
        h, rem = divmod(uptime, 3600); m, s = divmod(rem, 60)
        me = await client.get_me()
        owner = (f"{getattr(me, 'first_name', '') or ''} {getattr(me, 'last_name', '') or ''}").strip() or "Unknown"
        uname = f" (@{me.username})" if me.username else ""
        await msg.edit(f"🏓 **Ping:** `{ping_ms:.2f} ms`\n⏰ **Uptime:** `{h}h:{m:02d}m:{s:02d}s`\n⭐ **Owner:** [{owner}](tg://user?id={me.id}){uname}")
