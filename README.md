# 🤖 RamsBot

Bot Telegram VIP berbasis **Telethon** dan **python-telegram-bot**. User berlangganan VIP, menghubungkan akun Telegram mereka (session), lalu memakai fitur eksklusif lewat perintah titik (`.dl`, `.copy`, dan seterusnya) atau lewat menu bot. Tersedia juga Mini App web (repo terpisah) dan panel admin di dalam bot.

**Navigasi cepat:** [Fitur](#fitur) · [Mulai cepat](#mulai-cepat) · [Konfigurasi](#konfigurasi) · [Deploy](#deploy) · [Dokumentasi](#dokumentasi) · [Tes](#tes)

---

## Fitur

Perintah titik diketik dari **akun Telegram kamu sendiri** di chat mana saja (bukan dikirim ke bot). Perintah yang kamu ketik otomatis terhapus, dan hasilnya masuk ke **Saved Messages**.

| Fitur | Perintah | Keterangan |
|---|---|---|
| Media timer / view once | `.dl` (balas pesan), **Auto DL** | Simpan foto atau video sekali lihat. Auto DL hanya di chat pribadi |
| Channel/grup restricted | `.copy (link)` | Salin pesan dari channel atau grup yang dibatasi. Akunmu harus sudah bergabung |
| Story | `.story (link)` | Unduh story Telegram |
| Broadcast | `.bc (pesan)`, `.cancel #id` | Kirim pesan ke semua grup, kecuali yang di-blacklist |
| Blacklist broadcast | `.addbl`, `.delbl`, `.listbl` | Lewati grup tertentu (`.addbl` dijalankan di dalam grup, atau pakai ID) |
| Auto approve | `.acceptall`, `.stopaccept` | Setujui semua permintaan join channel |
| Auto Block Leaver | Menu bot | Blokir otomatis anggota yang keluar dari channel pilihan |
| QRIS dinamis | `.qris (nominal)` | Ubah QRIS statis jadi dinamis. Contoh: `.qris 25000`, `.qris 25k`, `.qris 1,5jt` |
| Ping | `.ping` (di Saved Messages) | Cek session aktif dan lama responsnya |
| **Rich Post** | Menu bot | Posting ke channel/grup dengan format Rich Messages ([panduan](docs/RICH_POST.md)) |
| Pengingat VIP | Otomatis | Notifikasi H-3 dan H-1 sebelum VIP habis |

> Perintah titik dan Auto Block Leaver butuh **session aktif**. **Rich Post** berjalan sepenuhnya lewat bot, tanpa session.

**Setup QRIS dinamis:** Bot → 🎯 Fitur VIP → 💳 QRIS Dinamis → kirim gambar QRIS statis (atau tempel kodenya). Hasil `.qris` dikirim di chat tempat perintah diketik.

---

## Mulai cepat

### Untuk user

1. Kirim `/start` ke bot.
2. **Beli VIP** (bayar QRIS lalu kirim bukti), klaim **voucher**, atau coba trial. Lihat [Pembayaran](docs/PEMBAYARAN.md).
3. Tekan **✨ Setup Bot** (atau `/setup`) dan ikuti 3 langkah:

   ```
   1. Kirim nomor HP   →  +6281234567890
   2. Kirim kode OTP   →  1 2 3 4 5        (pakai spasi antar angka agar kode tidak hangus)
   3. Kirim password 2FA (jika diaktifkan)
   ```

4. Pakai fitur lewat perintah titik atau menu **🎯 Fitur VIP**. Session tersimpan di database dan dimuat otomatis setiap bot restart.

### Untuk pemilik bot

1. Siapkan bot di [@BotFather](https://t.me/BotFather) dan API ID/Hash di [my.telegram.org](https://my.telegram.org).
2. Deploy ([panduan di bawah](#deploy)) dengan [environment variables](#konfigurasi) yang wajib.
3. Kirim `/admin`, lalu atur **QRIS penerima** dan **paket** di menu Pembayaran. Lihat [Panel Admin](docs/ADMIN.md).

---

## Konfigurasi

Set di Railway (atau `.env` untuk lokal).

| Variable | Wajib | Keterangan |
|---|:---:|---|
| `BOT_TOKEN` | ✅ | Token bot dari [@BotFather](https://t.me/BotFather) |
| `ADMIN_ID` | ✅ | Telegram user ID admin |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `API_ID` | ✅ | API ID dari [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | ✅ | API Hash dari [my.telegram.org](https://my.telegram.org) |
| `RESTRICTED_CHANNELS` | ❌ | JSON array channel ID yang diblokir, contoh `[-1001234, -1005678]` (default `[]`) |
| `LOG_CHANNEL_ID` | ❌ | ID channel log admin (default `0` = nonaktif) |
| `BACKUP_CHANNEL_ID` | ❌ | Channel tujuan auto backup, bisa juga diatur dari menu admin (default `0`) |
| `ADMIN_CONTACT` | ❌ | Kontak admin yang tampil ke user (default `@kqrbit`) |
| `BOT_NAME` | ❌ | Nama di header bot (default `RamsBot`) |
| `WEBAPP_URL` | ❌ | URL Mini App tanpa garis miring di akhir. Mengaktifkan tombol **Buka Mini App** dan **Console Web** |

---

## Deploy

### Railway

1. Fork atau push repo ini ke GitHub.
2. Buat project di [Railway](https://railway.app) dan tambahkan plugin **PostgreSQL**.
3. Set environment variable di atas.
4. Deploy. Railway menjalankan `python main.py` (lihat `railway.json`, Python 3.12). Tabel dibuat otomatis oleh `init_db()` dan data lama aman.

### Lokal

```bash
git clone https://github.com/gfrrmd/RamsBot.git
cd RamsBot
pip install -r requirements.txt

export BOT_TOKEN=...  ADMIN_ID=...  DATABASE_URL=...  API_ID=...  API_HASH=...
python main.py
```

---

## Dokumentasi

| Dokumen | Isi |
|---|---|
| [docs/RICH_POST.md](docs/RICH_POST.md) | Rich Post: alur, opsi format, blok, tombol dalam teks, keamanan |
| [docs/PEMBAYARAN.md](docs/PEMBAYARAN.md) | Alur beli VIP, auto-verifikasi OCR, Token VIP, kode promo, voucher |
| [docs/ADMIN.md](docs/ADMIN.md) | Menu bot dan admin, backup, Bersihkan Data |
| [docs/PENGEMBANGAN.md](docs/PENGEMBANGAN.md) | Struktur proyek, skema database, cara menambah fitur, tes |

---

## Tes

```bash
python tests/test_codes.py      # token, kode promo/voucher, limiter
python tests/test_receipt.py    # parser bukti bayar
python tests/test_rich.py       # Rich HTML, parser, klien API (jaringan di-mock)
```

---

## Tech stack dan lisensi

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) 21.11.1: Bot API handler
- [Telethon](https://github.com/LonamiWebs/Telethon): MTProto client (session user)
- [PostgreSQL](https://www.postgresql.org/) + [psycopg2](https://pypi.org/project/psycopg2/): database
- [httpx](https://www.python-httpx.org/) (dependensi bawaan python-telegram-bot): panggilan langsung `sendRichMessage`
- [Railway](https://railway.app): hosting

**Lisensi:** private, tidak untuk didistribusikan ulang tanpa izin.
