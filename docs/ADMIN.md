# 🛡️ Panel Admin

Menu admin, backup, dan pembersihan data.

[← Kembali ke README](../README.md)

**Isi dokumen:** [Menu bot](#menu-bot) · [Menu admin](#menu-admin) · [Bersihkan Data](#bersihkan-data)

---

## Menu bot

| Peran | Perintah | Isi menu |
|---|---|---|
| User | `/start` | Setup Bot, Fitur VIP, Beli VIP, Akun Saya, Panduan. Status akun, Token VIP, dan Klaim Voucher ada di *Akun Saya*. *Fitur VIP* berisi satu tombol per fitur dengan panduannya sendiri. Jika `WEBAPP_URL` diisi, muncul tombol **Buka Mini App** |
| Admin | `/admin` | Statistik, Pembayaran, Pengguna, Promosi, Blacklist, Data, dan tombol **Console Web** (jika `WEBAPP_URL` diisi) |

## Menu admin

Perintah admin: `/admin`, `/stats`, `/backup`, `/gift`, `/revoke`.

| Menu | Deskripsi |
|---|---|
| 📊 Statistik | User, VIP aktif/expired, session online, order, pendapatan |
| 💳 Pembayaran | Set QRIS penerima, kelola paket dan harga, kode unik, batas waktu, verifikasi order, auto-verifikasi |
| 👥 Pengguna | List VIP berpaginasi, Cek User (kartu dengan tombol +7/+30 hari dan revoke), Gift, Revoke, Pengumuman (teks/media ke semua user) |
| 🏷️ Promosi | Kode Promo dan Voucher |
| 🔒 Blacklist | Channel yang tidak bisa diunduh lewat `.copy` oleh siapa pun |
| 🗄️ Data | Info ukuran dan jumlah data, Backup DB, Restore DB (`.sql` / `.sql.gz`), Auto Backup, Bersihkan Data |

**Auto Backup:** jadwal 6j/12j/24j/3h/7h dikirim ke PM admin (dan channel opsional) sebagai `.sql.gz`.

## Bersihkan Data

Panel Admin → Data → Bersihkan Data. Satu tombol, tanpa batas waktu.

| Data yang dihapus | Keterangan |
|---|---|
| User | Belum pernah membeli, VIP expired atau dicabut, pemakai trial (trial bisa dipakai lagi), dan sisa data yatim |
| Session, langganan, pengaturan, QRIS, blacklist broadcast, auto block, token VIP | Milik user yang dihapus |
| Pesanan | Semua riwayat milik user yang dihapus, serta pesanan expired/cancelled/rejected milik siapa pun |
| Voucher dan kode promo | Yang sudah habis diklaim atau kedaluwarsa |

**Dipertahankan:** akun admin, VIP dan trial yang masih aktif (termasuk riwayat pesanannya), user dengan pesanan menunggu bayar/verifikasi, paket, pengaturan bot, blacklist channel, serta voucher dan promo yang masih berlaku. Dua pengecualian agar kuota tidak bisa diakali: pesanan lunas yang memakai kode promo berkuota yang masih aktif tetap disimpan, dan klaim voucher hanya dihapus bersama vouchernya.

Pembersihan menampilkan jumlah pasti lebih dulu, meminta konfirmasi, mengirim backup ke admin, lalu menghapus dalam satu transaksi. Statistik pendapatan berkurang sesuai pesanan lunas yang dihapus.
