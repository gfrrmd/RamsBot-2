import asyncio
import time

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import APP_VERSION, DEVICE_MODEL, LANG_CODE, SYSTEM_LANG_CODE, SYSTEM_VERSION

active_clients: dict[int, TelegramClient] = {}
dl_locks: dict[int, asyncio.Lock] = {}
_start_time: dict[int, float] = {}


def build_client(api_id, api_hash, session_string=""):
    return TelegramClient(
        StringSession(session_string),
        api_id,
        api_hash,
        device_model=DEVICE_MODEL,
        system_version=SYSTEM_VERSION,
        app_version=APP_VERSION,
        lang_code=LANG_CODE,
        system_lang_code=SYSTEM_LANG_CODE,
    )


async def stop_client_for_user(user_id: int):
    from utils.helpers import dl_seen

    client = active_clients.pop(user_id, None)
    if client:
        try:
            if client.is_connected():
                await client.disconnect()
            print(f"🔴 Client dihentikan untuk user {user_id}")
        except Exception as e:
            print(f"⚠️ Gagal disconnect client user {user_id}: {e}")
    dl_locks.pop(user_id, None)
    dl_seen.pop(user_id, None)
    _start_time.pop(user_id, None)
