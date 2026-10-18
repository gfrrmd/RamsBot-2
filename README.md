# 🤖 RamsBot

Bot Telegram VIP berbasis **Telethon** yang memungkinkan user berlangganan dan menghubungkan akun Telegram mereka untuk menggunakan fitur-fitur eksklusif.

---

## ✨ Fitur

### 👤 User (VIP)
| Fitur | Deskripsi |
|---|---|
| Beli / Perpanjang VIP | Bayar langsung di bot via QRIS dinamis, kirim bukti, admin approve. Perpanjang = sisa hari ditambah otomatis |
| `/setup` | Hubungkan akun Telegram (nomor HP + OTP + 2FA) |
| `.dl` / Auto DL | Download media timer & view-once |
| `.copy (link)` | Salin pesan dari channel/grup restricted |
| `.story (link)` | Download story |
| `.bc (pesan)` | Broadcast ke semua grup (+ blacklist `.addbl` `.delbl` `.listbl`) |
| `.acceptall` / `.stopaccept` | Auto approve join request |
| Auto Block Leaver | Blokir otomatis member yang keluar dari channel pilihan |
| `.ping` | Cek koneksi session |
| **`.qris (nominal)`** 🆕 | Ubah QRIS statis → dinamis. Contoh: `.qris 25000`, `.qris 25k`, `.qris 1,5jt` |
| Pengingat VIP 🆕 | Notifikasi H-3 & H-1 sebelum VIP habis |

**Setup QRIS:** Bot → 🎯 Fitur VIP → 💳 QRIS Dinamis → kirim gambar QRIS statis (atau tempel kode QRIS).
Hasil `.qris` dikirim di chat tempat command diketik.

### 🛡️ Admin (`/admin`, `/stats`, `/backup`)
| Fitur | Deskripsi |
|---|---|
| 📊 Statistik | User, VIP aktif/expired, session online, order, pendapatan |
| 💳 Pembayaran | Set QRIS penerima, kelola paket & harga, kode unik, batas waktu, verifikasi order |
| 💾 Auto Backup | Jadwal 6j/12j/24j/3h/7h → PM admin (+ channel opsional), `.sql.gz` |
| 👑 List VIP / 🔎 Cek User | Daftar VIP berpaginasi; kartu user dengan tombol +7/+30 hari & revoke |
| 📢 Pengumuman | Kirim pesan (teks/media) ke semua user bot |
| 🎁 Gift / 🚫 Revoke / 🔒 Blacklist / 📦 Backup / ♻️ Restore | Fitur lama, tetap ada (restore kini terima `.sql.gz`) |

### 💳 Alur Pembayaran
1. Admin: Panel Admin → Pembayaran → **Set QRIS Bayar** + **Kelola Paket** (`Nama | Hari | Harga`).
2. User: **Beli / Perpanjang VIP** → pilih paket → QRIS dinamis (nominal otomatis, +kode unik 1–99 jika ON).
3. User bayar → **Kirim Bukti Bayar**.
4. Admin menerima notifikasi bukti → cek mutasi → **Approve** → VIP aktif, session tersimpan otomatis jalan lagi.

> Verifikasi bersifat **manual** (QRIS statis tidak punya API notifikasi). Kode unik membantu mencocokkan mutasi.

---

## 🗂️ Struktur Proyek (tambahan v2)

```
ui.py                    # Helper tampilan HTML, format tanggal WIB, edit/kirim pesan aman
scheduler.py             # Auto backup, expire order, pengingat VIP
services/session_runner.py   # Jalankan ulang session Telethon setelah VIP aktif
utils/qris.py            # CRC16, parser TLV, validator, konversi statis→dinamis, decode & render QR
user/qris.py             # .qris + menu setup QRIS
user/payment.py          # Alur beli/perpanjang di sisi user
user/inputs.py           # Router upload gambar (QRIS / bukti bayar)
admin/payments.py        # Pengaturan pembayaran, paket, approve/tolak
admin/panel.py           # Statistik, list VIP, cek user, pengumuman
admin/autobackup.py      # Auto backup
```

---

## ⚙️ Environment Variables

Tambahkan variabel berikut di Railway (atau `.env` untuk lokal):

| Variable | Wajib | Keterangan |
|---|---|---|
| `BOT_TOKEN` | ✅ | Token bot dari [@BotFather](https://t.me/BotFather) |
| `ADMIN_ID` | ✅ | Telegram user ID admin |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `API_ID` | ✅ | API ID dari [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | ✅ | API Hash dari [my.telegram.org](https://my.telegram.org) |
| `RESTRICTED_CHANNELS` | ❌ | JSON array channel ID yang diblokir, contoh: `[-1001234, -1005678]` |
| `LOG_CHANNEL_ID` | ❌ | ID channel log admin |
| `BACKUP_CHANNEL_ID` | ❌ | Channel tujuan auto backup (bisa juga diatur dari menu admin) |
| `ADMIN_CONTACT` | ❌ | Kontak admin yang tampil ke user (default `@kqrbit`) |
| `BOT_NAME` | ❌ | Nama di header bot (default `RamsBot`) |

---

## 🚀 Deploy ke Railway

1. Fork atau push repo ini ke GitHub
2. Buat project baru di [Railway](https://railway.app)
3. Tambahkan **PostgreSQL** plugin di Railway
4. Set semua environment variables di atas
5. Deploy — Railway menjalankan `python main.py` (lihat `railway.json`, Python 3.12). Tabel baru dibuat otomatis oleh `init_db()`, data lama aman.

### Jalankan Lokal

```bash
# Clone repo
git clone https://github.com/gfrrmd/RamsBot.git
cd RamsBot

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BOT_TOKEN=...
export ADMIN_ID=...
export DATABASE_URL=...
export API_ID=...
export API_HASH=...

# Jalankan
python main.py
```

---

## 🔄 Alur Setup User

Setelah user berlangganan VIP, user cukup ketik `/setup` dan ikuti 3 langkah berikut:

```
1. Kirim nomor HP  →  +6281234567890
2. Kirim kode OTP  →  1 2 3 4 5
3. Kirim password 2FA (jika diaktifkan)
```

Session Telethon disimpan di database dan di-load otomatis setiap bot restart.

---

## 🗄️ Skema Database

| Tabel | Deskripsi |
|---|---|
| `users` | Data profil user (user_id, username, full_name) |
| `sessions` | String session Telethon per user |
| `subscriptions` | Data VIP (plan, paid_at, expired_at, is_active) |
| `user_settings` | Pengaturan per user (misal: auto_dl_view_once) |
| `bot_settings` | 🆕 Pengaturan bot (QRIS bayar, auto backup, dll) |
| `user_qris` | 🆕 QRIS statis per user VIP |
| `plans` | 🆕 Paket VIP & harga |
| `orders` | 🆕 Pesanan pembayaran |
| `blacklist_channels` | Daftar channel yang diblokir admin |
| `bc_group_blacklist` | Daftar grup yang diblokir per user untuk broadcast |

---

## 🧩 Cara Tambah Fitur Baru

### Command biasa (misal `/status`)
1. Buat `user/status.py` dengan fungsi `cmd_status(update, context)`
2. Di `main.py`: import fungsi → `app.add_handler(CommandHandler("status", cmd_status))`

### Fitur pakai Telethon client
1. Buat `user/fitur.py` dengan fungsi `register_fitur_handler(client, user_id)`
2. Di `auth/setup.py`: tambahkan `register_fitur_handler(client, user_id)` di dalam `register_telethon_handlers()`

### Fitur butuh data baru
1. Tambahkan fungsi di `database.py`
2. Tambahkan `CREATE TABLE IF NOT EXISTS ...` di `init_db()`

---

## 🛠️ Tech Stack

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v20+ — Bot API handler
- [Telethon](https://github.com/LonamiWebs/Telethon) — MTProto client (user session)
- [PostgreSQL](https://www.postgresql.org/) + [psycopg2](https://pypi.org/project/psycopg2/) — Database
- [Railway](https://railway.app) — Hosting & deployment

---

## 📄 Lisensi

Private — tidak untuk didistribusikan ulang tanpa izin.
