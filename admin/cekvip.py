from datetime import datetime

from telethon import events

from config import ADMIN_ID
from database import get_all_vip_users


def register(client):
    @client.on(events.NewMessage(pattern=r"^\.cekvip$", outgoing=True))
    async def cekvip_handler(event):
        if event.sender_id != ADMIN_ID:
            return

        await event.edit("⏳ Mengambil data VIP...")

        vip_list = get_all_vip_users()

        if not vip_list:
            await event.edit("📋 **List User VIP**\n\n_Belum ada user VIP aktif._")
            return

        now = datetime.now()
        lines = [f"👑 **List User VIP** ({len(vip_list)} user)\n"]

        for i, u in enumerate(vip_list, start=1):
            user_id = u["user_id"]
            full_name = u["full_name"] or "-"
            username = f"@{u['username']}" if u["username"] else "-"
            paid_at = u["paid_at"]
            expired_at = u["expired_at"]

            try:
                start_dt = datetime.fromisoformat(paid_at)
                start_str = start_dt.strftime("%d %b %Y")
            except Exception:
                start_str = "-"

            try:
                exp_dt = datetime.fromisoformat(expired_at)
                exp_str = exp_dt.strftime("%d %b %Y")
                sisa = (exp_dt - now).days
                sisa_str = f"{sisa} hari lagi" if sisa > 0 else "⚠️ Expired"
            except Exception:
                exp_str = "-"
                sisa_str = "-"

            lines.append(
                f"{i}. [{full_name}](tg://user?id={user_id}) ({username}) | `{user_id}`\n"
                f"   📅 Mulai VIP : {start_str}\n"
                f"   ⏳ Expired   : {exp_str} ({sisa_str})\n"
            )

        await event.edit("\n".join(lines), parse_mode="md", link_preview=False)
