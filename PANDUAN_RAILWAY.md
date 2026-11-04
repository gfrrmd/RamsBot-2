# Deploy RamsBot di Railway

## 1. Siapkan repo
1. Upload isi folder ini ke repo GitHub (private disarankan). File `.env` jangan ikut ter-upload (sudah ada di `.gitignore`).

## 2. Buat project di Railway
1. **New Project → Deploy from GitHub repo** → pilih repo bot.
2. Di project yang sama: **New → Database → Add PostgreSQL**.

## 3. Isi Variables
1. Buka service bot → tab **Variables** → **Raw Editor**.
2. Tempel isi `.env.example`, isi nilainya.
3. Variabel `DATABASE_URL` biarkan bernilai `${{Postgres.DATABASE_URL}}` (ganti `Postgres` jika nama service database kamu berbeda).
4. Klik **Update Variables**. Railway akan deploy ulang otomatis.

| Variable | Wajib |
|---|:---:|
| `BOT_TOKEN`, `ADMIN_ID`, `API_ID`, `API_HASH`, `DATABASE_URL` | ✅ |
| `LOG_CHANNEL_ID`, `BACKUP_CHANNEL_ID`, `RESTRICTED_CHANNELS`, `ADMIN_CONTACT`, `BOT_NAME`, `WEBAPP_URL` | ❌ |

## 4. Cek hasilnya
- Tab **Deployments → View Logs**: bot siap bila tidak ada error dan tabel dibuat otomatis oleh `init_db()`.
- Kirim `/start` ke bot.

## Database lama (dari Railway sebelumnya)
Pakai database PostgreSQL yang sama: cukup arahkan `DATABASE_URL` ke database itu. Data lama aman. Tabel fitur baru (`gban_list`, `userbot_settings`, `rich_popups`, `rich_polls`, `rich_votes`) dibuat otomatis tanpa menyentuh tabel lama.

## Memindahkan data dari versi Termux
Kirim file backup `.sql.gz` dari Termux lewat menu admin di bot: **Data → Restore**. Baris yang sudah ada tidak ditimpa. Cek hasilnya setelah restore.

## Catatan
- Railway memakai `railway.json` (start command `python main.py`, restart otomatis saat gagal) dan Python 3.12.
- Verifikasi bukti bayar otomatis (OCR) membutuhkan paket di `requirements.txt` dan `railpack.json` (`libgl1`, `libglib2.0-0`). Keduanya sudah disertakan.
- Karena memakai OCR, build pertama bisa memakan beberapa menit.
