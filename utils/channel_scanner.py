from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.types import ChannelParticipantCreator, ChannelParticipantAdmin


async def get_admin_channels(client, expected_user_id: int) -> list[dict]:
    """
    Kembalikan semua channel/grup di mana user adalah Creator atau Admin.
    expected_user_id dipakai untuk memastikan client yang jalan memang milik user yang benar.
    """
    result = []
    try:
        me = await client.get_me()

        # Guard: pastikan client ini benar-benar milik user yang request
        if me.id != expected_user_id:
            print(f"[ChannelScanner] Mismatch! client.me={me.id}, expected={expected_user_id}")
            return []

        async for dialog in client.iter_dialogs():
            if not dialog.is_channel:
                continue
            try:
                p = await client(GetParticipantRequest(dialog.id, me.id))
                if isinstance(p.participant, (ChannelParticipantCreator, ChannelParticipantAdmin)):
                    result.append({
                        "id": dialog.id,
                        "name": dialog.name or str(dialog.id),
                    })
            except Exception:
                continue
    except Exception as e:
        print(f"[ChannelScanner] Error: {e}")
    return result
