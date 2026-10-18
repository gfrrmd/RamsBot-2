"""Menjalankan (kembali) client Telethon milik user dari session yang tersimpan."""
import asyncio
import time

from client_manager import _start_time, active_clients, build_client, dl_locks
from config import API_HASH, API_ID
from database import get_user_session, is_subscribed


async def ensure_client_running(user_id: int, bot=None) -> str:
    """
    Pastikan client Telethon user hidup.
    Return: 'already' | 'started' | 'no_session' | 'not_subscribed' | 'failed:<alasan>'
    """
    client = active_clients.get(user_id)
    if client and client.is_connected():
        return "already"
    if not is_subscribed(user_id):
        return "not_subscribed"
    sess = get_user_session(user_id)
    if not sess:
        return "no_session"

    from auth.setup import register_telethon_handlers   # import lokal: hindari circular import

    new_client = build_client(API_ID, API_HASH, sess["string_session"])
    try:
        await new_client.connect()
        if not await new_client.is_user_authorized():
            await new_client.disconnect()
            return "failed:session tidak valid (akun sudah logout), user perlu /setup ulang"
        dl_locks.setdefault(user_id, asyncio.Lock())
        _start_time[user_id] = time.monotonic()
        register_telethon_handlers(new_client, user_id, bot_client=bot)
        active_clients[user_id] = new_client
        asyncio.ensure_future(new_client.run_until_disconnected())
        print(f"✅ Session user {user_id} dijalankan ulang.")
        return "started"
    except Exception as e:
        try:
            await new_client.disconnect()
        except Exception:
            pass
        print(f"⚠️ Gagal menjalankan session user {user_id}: {e}")
        return f"failed:{e}"
