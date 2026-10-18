import time
import asyncio

_active_tasks: dict[str, asyncio.Task] = {}


def _make_task_id(user_id: int) -> str:
    return str(int(time.time()))[-5:]


def register_cancel_task_handler(client):
    from telethon import events

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.cancel\s+#?(\S+)$"))
    async def cancel_handler(event):
        task_id = event.pattern_match.group(1).strip()
        task = _active_tasks.get(task_id)
        await event.delete()
        if task and not task.done():
            task.cancel()
            _active_tasks.pop(task_id, None)
            await client.send_message("me", f"⛔ Task `#{task_id}` berhasil dibatalkan.")
        else:
            await client.send_message("me", f"⚠️ Task `#{task_id}` tidak ditemukan atau sudah selesai.")
