from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from auth.states import clear_input_waits
from client_manager import active_clients
from config import ADMIN_CONTACT
from database import (
    add_auto_block_channel,
    bc_blacklist_get,
    get_auto_block_channels,
    get_auto_dl_view_once,
    get_user_session,
    remove_auto_block_channel,
    set_auto_dl_view_once,
)
from keyboards import (
    back_to_fitur_keyboard,
    bc_blacklist_keyboard,
    beli_keyboard,
    broadcast_keyboard,
    fitur_vip_keyboard,
    main_keyboard,
    timer_keyboard,
    tos_keyboard,
)
from ui import build_home_text, edit_or_send, esc, header, session_badge
from user.subscription import build_subscription_text
from utils.channel_scanner import get_admin_channels

_STATUS_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("💎 Beli / Perpanjang VIP", callback_data="pay_menu")],
    [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_back")],
])


async def _show_auto_block_menu(query, uid):
    client = active_clients.get(uid)
    if not client or not client.is_connected():
        await edit_or_send(query, "❌ Session belum aktif. Lakukan /setup dulu.", back_to_fitur_keyboard())
        return

    # Kirim uid sebagai expected_user_id agar tidak bocor ke akun lain
    channels = await get_admin_channels(client, expected_user_id=uid)
    watched_ids = {ch["channel_id"] for ch in get_auto_block_channels(uid)}

    if not channels:
        await edit_or_send(query, f"{header('😔', 'Auto Block Leaver')}\nKamu tidak ditemukan sebagai admin di channel/grup manapun.",
                           back_to_fitur_keyboard())
        return

    buttons = []
    for ch in channels:
        status = "✅" if ch["id"] in watched_ids else "☑️"
        buttons.append([InlineKeyboardButton(f"{status} {ch['name']}", callback_data=f"abl_toggle_{ch['id']}")])
    buttons.append([InlineKeyboardButton("🔙 Kembali ke Fitur VIP", callback_data="menu_fitur")])

    await edit_or_send(
        query,
        f"{header('🔒', 'Auto Block Leaver')}\n"
        "Pilih channel yang ingin dipantau.\n"
        "Jika seseorang keluar dari channel yang aktif (✅), akun mereka akan otomatis diblokir dari akun Telegram kamu.\n\n"
        "✅ = aktif  |  ☑️ = nonaktif",
        InlineKeyboardMarkup(buttons),
    )


async def user_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = query.from_user.id
    if data == "menu_admin" or data.startswith("admin_") or data.startswith("bl_"):
        return
    await query.answer()
    clear_input_waits(uid)

    if data == "menu_back":
        await edit_or_send(query, build_home_text(query.from_user), main_keyboard(uid))
        return

    if data == "tos_close":
        try:
            await query.delete_message()
        except Exception:
            await query.edit_message_text("❌ Ditutup.", reply_markup=None)
        return

    if data == "menu_setup":
        if get_user_session(uid):
            await edit_or_send(
                query,
                f"{header('⚙️', 'Session Terpasang')}\nStatus: {session_badge(uid)}\n\nKirim /setup untuk setup ulang.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_back")]]),
            )
        else:
            await edit_or_send(
                query,
                f"{header('📋', 'Kebijakan & Ketentuan')}\n"
                "Sebelum melanjutkan, harap baca dan pahami hal berikut:\n\n"
                "1. <b>Akses Sesi</b> — Kamu memberikan akses sesi login Telegram kamu kepada bot ini untuk menjalankan fitur VIP.\n\n"
                "2. <b>Tanggung Jawab</b> — Segala aktivitas yang dilakukan melalui sesi ini sepenuhnya menjadi tanggung jawab kamu. Risiko ditanggung sendiri.\n\n"
                "3. <b>Larangan</b> — Dilarang menggunakan fitur ini untuk spam, penipuan, atau aktivitas yang melanggar ketentuan Telegram maupun hukum yang berlaku.\n\n"
                "4. <b>Keamanan</b> — Kami tidak menyimpan password atau kode OTP kamu. Keamanan akun sepenuhnya menjadi tanggung jawab kamu.\n\n"
                "5. <b>Pencabutan Akses</b> — Kamu dapat menghapus sesi kapan saja melalui Pengaturan Telegram, menu Perangkat Aktif.\n\n"
                "Dengan menekan <b>Saya Setuju</b>, kamu menyatakan telah membaca dan menyetujui seluruh ketentuan di atas.",
                tos_keyboard(),
            )
        return

    if data == "menu_subscription":
        user = query.from_user
        await edit_or_send(query, build_subscription_text(uid, full_name=user.full_name, username=user.username), _STATUS_KB)
        return
    if data == "menu_fitur":
        await edit_or_send(query, f"{header('🎯', 'Fitur VIP')}\nPilih fitur di bawah:", fitur_vip_keyboard())
        return
    if data == "menu_beli":
        await edit_or_send(
            query,
            f"{header('📖', 'Panduan Penggunaan')}\n"
            "<b>1.</b> 💎 Beli VIP lewat tombol <b>Beli / Perpanjang VIP</b> (bayar QRIS, kirim bukti).\n"
            "<b>2.</b> ✨ Tekan <b>Setup Bot</b> lalu login akun Telegram kamu (nomor HP → OTP → 2FA bila ada).\n"
            "<b>3.</b> 🎯 Pakai fitur lewat command di chat Telegram mana pun.\n\n"
            f"\n<b>Command singkat</b>\n"
            "<code>.dl</code> (reply media timer) - <code>.copy (link)</code> - <code>.story (link)</code>\n"
            "<code>.bc (pesan)</code> - <code>.qris (nominal)</code> - <code>.acceptall</code> - <code>.ping</code>\n\n"
            f"Pertanyaan lain? Hubungi admin {esc(ADMIN_CONTACT)}",
            beli_keyboard(),
        )
        return
    if data == "fitur_timer":
        await edit_or_send(
            query,
            f"{header('⏱️', 'Download Media Timer & View Once')}\n"
            "Simpan foto/video timer yang hanya bisa dilihat sekali (view once).\n\n"
            "📲 <b>Cara pakai - Manual:</b>\nBalas pesan view once/timer dengan perintah:\n<code>.dl</code>\n\n"
            "🤖 <b>Cara pakai - Auto DL (Otomatis):</b>\nAktifkan Auto DL agar bot otomatis menyimpan setiap media view once yang masuk ke chat kamu.\n\n"
            "Gunakan tombol di bawah untuk ON/OFF.",
            timer_keyboard(uid),
        )
        return
    if data == "vip_toggle_auto_dl":
        current = get_auto_dl_view_once(uid)
        set_auto_dl_view_once(uid, not current)
        await edit_or_send(query, f"{header('⏱️', 'Auto DL View Once')}\nSekarang: {'ON ✅' if not current else 'OFF ❌'}", timer_keyboard(uid))
        return
    if data == "fitur_copy":
        await edit_or_send(
            query,
            f"{header('📥', 'Download dari Channel/Grup Private')}\n"
            "Download pesan, foto, atau video dari channel/grup yang dibatasi (restricted/tidak bisa di-forward).\n\n"
            "📝 <b>Cara pakai:</b>\nKetik dimanapun dengan command:\n<code>.copy (link postingan)</code>\n\n"
            "💡 <b>Contoh:</b>\n<code>.copy https://t.me/koleksijee/456</code>",
            back_to_fitur_keyboard(),
        )
        return
    if data == "fitur_story":
        await edit_or_send(
            query,
            f"{header('🎥', 'Download Story')}\n"
            "Download story Telegram milik orang lain langsung dari link story-nya.\n\n"
            "📝 <b>Cara pakai:</b>\nKirim link story yang ingin didownload:\n<code>.story (link story)</code>\n\n"
            "💡 <b>Contoh:</b>\n<code>.story https://t.me/username/s/7</code>",
            back_to_fitur_keyboard(),
        )
        return
    if data == "fitur_ping":
        await edit_or_send(
            query,
            f"{header('🏓', 'Ping')}\n"
            "Cek apakah koneksi session Telethon kamu masih aktif dan berapa lama waktu responnya.\n\n"
            "📝 <b>Cara pakai:</b>\nBuka Saved Messages di Telegram kamu, lalu kirim:\n<code>.ping</code>\n\n"
            "💡 <b>Contoh hasil:</b>\n🏓 Pong! 42ms",
            back_to_fitur_keyboard(),
        )
        return
    if data == "fitur_broadcast":
        await edit_or_send(
            query,
            f"{header('📢', 'Broadcast')}\n"
            "Kirim pesan yang sama ke semua grup yang kamu join secara otomatis.\n\n"
            "📝 <b>Cara pakai:</b>\nKetik command berikut dari chat manapun:\n<code>.bc (pesan kamu)</code>\n\n"
            "💡 <b>Contoh:</b>\n<code>.bc Hai, ada yang mau berteman?</code>\n\n"
            "🚫 <b>Batalkan broadcast:</b>\n<code>.cancel #task_id</code>",
            broadcast_keyboard(),
        )
        return
    if data == "fitur_acceptall":
        await edit_or_send(
            query,
            f"{header('✅', 'Auto Approve')}\n"
            "Approve semua join request di channel/grup kamu secara otomatis.\n\n"
            "📝 <b>Cara pakai:</b>\nJalankan command di dalam channel, atau sertakan username/link:\n"
            "<code>.acceptall</code>\n<code>.acceptall (username/link channel)</code>\n\n"
            "💡 <b>Contoh:</b>\n<code>.acceptall @namaChannel</code>\n\n"
            "⏹ <b>Untuk stop:</b>\n<code>.stopaccept</code>",
            back_to_fitur_keyboard(),
        )
        return
    if data == "fitur_autoblock":
        await _show_auto_block_menu(query, uid)
        return
    if data.startswith("abl_toggle_"):
        channel_id = int(data.split("abl_toggle_")[1])
        watched = {ch["channel_id"] for ch in get_auto_block_channels(uid)}
        if channel_id in watched:
            remove_auto_block_channel(uid, channel_id)
        else:
            client = active_clients.get(uid)
            channel_name = ""
            if client:
                try:
                    entity = await client.get_entity(channel_id)
                    channel_name = getattr(entity, "title", "") or ""
                except Exception:
                    pass
            add_auto_block_channel(uid, channel_id, channel_name)
        await _show_auto_block_menu(query, uid)
        return
    if data == "bc_blacklist_menu":
        rows = bc_blacklist_get(uid)
        bl_text = "📋 Blacklist kamu kosong.\nSemua grup akan menerima broadcast." if not rows else f"🚫 <b>{len(rows)} grup diblacklist.</b>"
        await edit_or_send(
            query,
            f"{header('⛔', 'Blacklist Broadcast')}\n{bl_text}\n\n"
            "Untuk mengelola blacklist, gunakan command:\n\n"
            "<code>.addbl</code> — Tambah ke blacklist\n"
            "<code>.addbl (ID Grup)</code> — Tambah ke blacklist by ID\n"
            "<code>.delbl</code> — Hapus blacklist\n"
            "<code>.delbl (ID Grup)</code> — Hapus blacklist by ID\n"
            "<code>.listbl</code> — Lihat list blacklist lengkap",
            bc_blacklist_keyboard(),
        )
        return
    if data == "bc_bl_list":
        rows = bc_blacklist_get(uid)
        if not rows:
            text = f"{header('📝', 'Blacklist BC Kosong')}\nSemua grup akan menerima broadcast kamu."
        else:
            lines = [header("🚫", f"Blacklist BC ({len(rows)} grup)")]
            for i, r in enumerate(rows, 1):
                lines.append(f"{i}. <b>{esc(r['group_name'] or '—')}</b>\n   <code>{r['group_id']}</code> <i>({(r.get('added_at') or '')[:10]})</i>")
            text = "\n".join(lines)
        await edit_or_send(query, text, bc_blacklist_keyboard())
