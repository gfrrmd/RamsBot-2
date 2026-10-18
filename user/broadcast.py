import asyncio

from telethon import events
from telethon.tl.types import Channel, Chat

from client_manager import stop_client_for_user
from database import bc_blacklist_add, bc_blacklist_get, bc_blacklist_ids, bc_blacklist_remove, is_subscribed
from user.tasks import _active_tasks, _make_task_id


def _normalize_gid(raw_id: int) -> int:
    s = str(raw_id)
    if s.startswith("-100"):
        return int(s[4:])
    if s.startswith("-"):
        return int(s[1:])
    return int(raw_id)


async def _resolve_group(client, event, arg):
    if arg:
        raw_id = int(arg)
        group_id = _normalize_gid(raw_id)
        try:
            entity = await client.get_entity(raw_id)
            group_name = getattr(entity, "title", "") or str(raw_id)
        except Exception:
            group_name = str(raw_id)
        return group_id, group_name
    chat = await event.get_chat()
    if not isinstance(chat, (Channel, Chat)):
        raise ValueError("⚠️ Command ini hanya bisa dipakai langsung di dalam grup, atau sertakan ID grup.\n\nContoh: `.addbl -1001234567890`")
    return _normalize_gid(chat.id), getattr(chat, "title", "") or str(chat.id)


async def _process_bc(client, text: str, status_msg, task_id: str, user_id: int):
    success = 0
    try:
        blocked_ids = bc_blacklist_ids(user_id)
        groups = []; seen_ids = set()
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if not isinstance(entity, (Channel, Chat)):
                continue
            eid = _normalize_gid(getattr(entity, "id", 0))
            if not eid or eid in seen_ids:
                continue
            if eid in blocked_ids:
                seen_ids.add(eid); continue
            is_broadcast_channel = isinstance(entity, Channel) and getattr(entity, "broadcast", False) and not getattr(entity, "megagroup", False)
            if not is_broadcast_channel:
                seen_ids.add(eid); groups.append(entity)
        total = len(groups); failed = 0; processed = 0; cancelled = False
        semaphore = asyncio.Semaphore(5)

        async def send_to_group(group):
            nonlocal success, failed, processed, cancelled
            if cancelled: return
            async with semaphore:
                if cancelled: return
                try:
                    await client.send_message(group, text); success += 1
                except Exception:
                    failed += 1
                finally:
                    processed += 1
                    if processed % 5 == 0 or processed == total:
                        try:
                            await status_msg.edit(f"📣 Memproses bc... ({processed}/{total})\n\nKetik `.cancel #{task_id}` untuk membatalkan bc.")
                        except Exception:
                            pass
                    await asyncio.sleep(0.5)
        batch_tasks = [asyncio.create_task(send_to_group(g)) for g in groups]
        try:
            await asyncio.gather(*batch_tasks)
        except asyncio.CancelledError:
            cancelled = True
            for t in batch_tasks: t.cancel()
            raise
        result = f"📣 **Pesan:** {text}\n✨ **Berhasil:** {success}\n☹️ **Gagal:** {failed}"
        if blocked_ids:
            result += f"\n😹 **Skip:** {len(blocked_ids)}"
        await status_msg.edit(result)
    except asyncio.CancelledError:
        try:
            await status_msg.edit(f"😭 Broadcast `#{task_id}` dibatalkan.\n\n✨ Terkirim sebelum cancel: {success} grup")
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            await status_msg.edit(f"😵 Broadcast gagal: {e}")
        except Exception:
            pass


def register_broadcast_handler(client, user_id: int):
    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.bc\s+(.+)$"))
    async def bc_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id); await event.client.send_message("me", "❌ Langganan VIP kamu sudah habis atau dicabut.\nHubungi admin untuk memperpanjang."); return
        text = event.pattern_match.group(1).strip(); await event.delete()
        task_id = _make_task_id(user_id)
        status_msg = await client.send_message("me", f"📣 Memproses bc...\n\nKetik `.cancel #{task_id}` untuk membatalkan bc.")
        task = asyncio.ensure_future(_process_bc(client, text, status_msg, task_id, user_id))
        _active_tasks[task_id] = task
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            _active_tasks.pop(task_id, None)

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.addbl(?:\s+(-?\d+))?$"))
    async def addbl_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id); await event.client.send_message("me", "❌ Langganan VIP kamu sudah habis atau dicabut."); return
        await event.delete()
        try:
            group_id, group_name = await _resolve_group(client, event, event.pattern_match.group(1))
        except ValueError as e:
            await client.send_message("me", str(e)); return
        added = bc_blacklist_add(user_id, group_id, group_name)
        await client.send_message("me", f"⛔ **{group_name}** ditambahkan ke blacklist bc.\n`{group_id}`" if added else f"⚠️ **{group_name}** (`{group_id}`) sudah ada di blacklist bc.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.delbl(?:\s+(-?\d+))?$"))
    async def delbl_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id); await event.client.send_message("me", "❌ Langganan VIP kamu sudah habis atau dicabut."); return
        await event.delete()
        try:
            group_id, group_name = await _resolve_group(client, event, event.pattern_match.group(1))
        except ValueError as e:
            await client.send_message("me", str(e)); return
        removed = bc_blacklist_remove(user_id, group_id)
        await client.send_message("me", f"✅ **{group_name}** dihapus dari blacklist bc.\n`{group_id}`" if removed else f"⚠️ **{group_name}** (`{group_id}`) tidak ada di blacklist bc.")

    @client.on(events.NewMessage(outgoing=True, pattern=r"^\.listbl$"))
    async def listbl_handler(event):
        if not is_subscribed(user_id):
            await stop_client_for_user(user_id); await event.client.send_message("me", "❌ Langganan VIP kamu sudah habis atau dicabut."); return
        await event.delete()
        rows = bc_blacklist_get(user_id)
        if not rows:
            await client.send_message("me", "📝 **Blacklist BC kosong.**\n\nSemua grup akan menerima broadcast kamu."); return
        lines = [f"🚫 **Blacklist BC** ({len(rows)} grup)\n"]
        for i, r in enumerate(rows, 1):
            lines.append(f"{i}. **{r['group_name'] or '—'}**\n   `{r['group_id']}`")
        lines.append("\n💡 Ketik `.delbl <id>` untuk whitelist kembali.")
        await client.send_message("me", "\n".join(lines))
