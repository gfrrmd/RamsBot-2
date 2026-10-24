# 🧑‍💻 Pengembangan

Struktur proyek, skema database, cara menambah fitur, dan menjalankan tes.

[← Kembali ke README](../README.md)

**Isi dokumen:** [Struktur proyek](#️-struktur-proyek) · [Skema database](#️-skema-database) · [Menambah fitur](#-menambah-fitur-baru) · [Tes](#-tes)

---

## 🗂️ Struktur proyek

```
main.py                    Titik masuk, pendaftaran handler
config.py                  Environment variable
database.py                Koneksi PostgreSQL, skema (init_db), fungsi data
keyboards.py               Semua keyboard inline
ui.py                      Format HTML, tanggal WIB, edit/kirim pesan aman
scheduler.py               Auto backup, expire order, pengingat VIP
client_manager.py          Registry client Telethon aktif

auth/                      Setup session (HP, OTP, 2FA) dan state input
services/session_runner.py Jalankan ulang session Telethon setelah VIP aktif

user/                      Fitur dan menu user
  start.py, callbacks.py     /start, menu, panduan Fitur VIP
  download.py, copy.py, story.py, auto_dl.py   .dl, .copy, .story, Auto DL
  broadcast.py, tasks.py     .bc, blacklist, .cancel
  join_request.py            .acceptall / .stopaccept
  auto_block_leaver.py       Auto Block Leaver
  qris.py                    .qris dan menu setup QRIS
  rich_post.py               🆕 Rich Post (menu, draf, pratinjau, posting)
  payment.py, vip_codes.py   Beli VIP, token, voucher, promo
  inputs.py                  Router input non-command (QRIS, bukti bayar, Rich Post)

admin/                     Panel admin (statistik, pembayaran, promo, data, backup)

utils/
  qris.py                    CRC16, parser TLV, validator, konversi, decode dan render QR
  rich.py                    🆕 Klien sendRichMessage dan pembangun Rich HTML
  receipt.py, codes.py       OCR bukti bayar, kode/token
  progress.py, media.py, log_media.py, helpers.py, channel_scanner.py

tests/                     Tes tanpa framework (python tests/<file>.py)
```

---

## 🗄️ Skema database

| Tabel | Deskripsi |
|---|---|
| `users` | Profil user (user_id, username, full_name) |
| `sessions` | String session Telethon per user |
| `subscriptions` | Data VIP (plan, paid_at, expired_at, is_active, reminder_stage) |
| `user_settings` | Pengaturan per user (misalnya `auto_dl_view_once`) |
| `bot_settings` | Pengaturan bot (QRIS bayar, auto backup, auto-verifikasi, dan lain-lain) |
| `user_qris` | QRIS statis per user VIP |
| `plans`, `orders` | Paket VIP dan pesanan pembayaran (termasuk `promo_id`, `promo_code`, `discount`) |
| `vip_tokens`, `vip_token_log` | Token VIP dan riwayat pemindahan |
| `promo_codes`, `vouchers`, `voucher_claims` | Kode promo, voucher, dan klaimnya |
| `blacklist_channels` | Channel yang diblokir admin untuk `.copy` |
| `bc_group_blacklist` | Grup yang dilewati per user saat broadcast |
| `auto_block_channels` | Channel pantauan Auto Block Leaver per user |
| `rich_targets` 🆕 | Channel/grup tujuan Rich Post per user (maks 20) |

Semua tabel dibuat otomatis oleh `init_db()`. Data lama aman.

---

## 🧩 Menambah fitur baru

**Command bot biasa** (misalnya `/status`)
1. Buat `user/status.py` dengan fungsi `cmd_status(update, context)`.
2. Di `main.py`, impor fungsinya lalu `app.add_handler(CommandHandler("status", cmd_status))`.

**Fitur menu dengan tombol** (contoh: `user/rich_post.py`)
1. Buat handler callback dengan prefix unik, lalu daftarkan di `main.py` **sebelum** `user_callback_handler`.
2. Tambahkan tombolnya di `keyboards.py` (`fitur_vip_keyboard`).
3. Jika butuh menunggu input pesan, simpan state di `auth/states.py` dan tambahkan cabangnya di `user/inputs.py`.

**Fitur pakai Telethon client** (perintah titik)
1. Buat `user/fitur.py` dengan fungsi `register_fitur_handler(client, user_id)`.
2. Di `auth/setup.py`, panggil di dalam `register_telethon_handlers()`.

**Fitur butuh data baru**
1. Tambahkan fungsi di `database.py`.
2. Tambahkan `CREATE TABLE IF NOT EXISTS ...` di `init_db()`.

---

## 🧪 Tes

```bash
python tests/test_codes.py      # token, kode promo/voucher, limiter
python tests/test_receipt.py    # parser bukti bayar
python tests/test_rich.py       # pembangun Rich HTML (blok, tombol dalam teks), parser, klien API (jaringan di-mock)
```
