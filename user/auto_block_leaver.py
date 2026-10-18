from telethon.tl.functions.contacts import BlockRequest

from client_manager import active_clients
from database import get_all_auto_block_channel_owners


async def handle_chat_member_left(update, context):
    """
    Dipanggil oleh ChatMemberHandler di main.py setiap kali status member berubah.
    Mendeteksi member yang keluar/dikick, lalu blokir via Telethon client milik owner channel.
    """
    result = update.chat_member
    if result is None:
        return

    old = result.old_chat_member
    new = result.new_chat_member

    # Hanya proses jika status berubah menjadi "left" atau "kicked"
    LEFT_STATUSES = ("left", "kicked", "banned")
    MEMBER_STATUSES = ("member", "restricted", "administrator", "creator")
    if old.status not in MEMBER_STATUSES or new.status not in LEFT_STATUSES:
        return

    chat_id = result.chat.id
    leaver = new.user

    # Jangan blokir bot atau akun anonim
    if leaver.is_bot:
        return

    # Cari semua user yang memantau channel ini
    owners = get_all_auto_block_channel_owners(chat_id)
    if not owners:
        return

    for owner_user_id in owners:
        client = active_clients.get(owner_user_id)
        if not client or not client.is_connected():
            print(f"[AutoBlock] Skip user_id={owner_user_id}: client tidak aktif")
            continue
        try:
            me = await client.get_me()
            # Jangan blokir diri sendiri
            if leaver.id == me.id:
                continue
            tl_user = await client.get_entity(leaver.id)
            await client(BlockRequest(tl_user))
            print(f"[AutoBlock] user_id={owner_user_id} | diblokir: {leaver.id} (@{leaver.username}) dari channel {chat_id}")
        except Exception as e:
            print(f"[AutoBlock] user_id={owner_user_id} | gagal blokir {leaver.id}: {e}")


def register_auto_block_leaver_handler(client, user_id: int):
    """
    Fungsi ini dipertahankan agar tidak ada ImportError dari auth/setup.py.
    Handler sesungguhnya sudah dipindah ke Bot API (ChatMemberHandler di main.py).
    """
    pass
