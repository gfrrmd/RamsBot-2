# 💳 Pembayaran dan Akses VIP

Alur pembelian, auto-verifikasi OCR, Token VIP, kode promo, dan voucher.

[← Kembali ke README](../README.md)

**Isi dokumen:** [Alur pembayaran](#alur-pembayaran) · [Auto-verifikasi OCR](#-auto-verifikasi-bukti-bayar-ocr) · [Token VIP](#-token-vip-pindah-vip-ke-akun-lain) · [Kode promo](#️-kode-promo-panel-admin--kode-promo) · [Voucher](#️-voucher-panel-admin--voucher)

---

## Alur pembayaran

1. **Admin:** Panel Admin → Pembayaran → **Set QRIS Bayar** dan **Kelola Paket** (format `Nama | Hari | Harga`).
2. **User:** *Beli / Perpanjang VIP* → pilih paket → QRIS dinamis (nominal otomatis, ditambah kode unik 1–99 jika aktif). Perpanjang berarti sisa hari ditambah otomatis.
3. User membayar, lalu **Kirim Bukti Bayar**.
4. Admin menerima notifikasi bukti, mengecek mutasi, lalu **Approve**. VIP aktif dan session tersimpan otomatis jalan lagi.

> Verifikasi bersifat **manual** karena QRIS statis tidak punya API notifikasi. Kode unik membantu mencocokkan mutasi.

## 🤖 Auto-verifikasi bukti bayar (OCR)

Bot dapat membaca screenshot bukti transfer dan menyetujui order otomatis.

**Aturan baca**
- **Wajib:** nominal pada gambar sama dengan total order (harga + kode unik).
- **Opsional:** tanggal dan jam transaksi. Jika terbaca, harus berada di antara waktu order dibuat dan batas bayar (toleransi 3 menit). Jam di status bar HP diabaikan. Jika tanggal/jam tidak terlihat, hanya nominal yang dicek.
- Zona waktu bukti dianggap WIB (WITA/WIT dikenali bila tertulis). Ubah default lewat `bot_settings` key `pay_tz_offset` (jam, default `7`).

**Hasil**

| Kondisi | Tindakan bot |
|---|---|
| Nominal cocok (+ waktu cocok atau tidak terlihat) | VIP aktif otomatis, admin menerima laporan + tombol **Batalkan Langganan** |
| Nominal tidak terbaca atau tidak cocok | User diminta kirim ulang (maks 3x), setelah itu diteruskan ke admin |
| Nominal cocok tapi waktu di luar rentang | Diteruskan ke admin (tidak di-approve otomatis) |
| Gambar identik dengan bukti order lain | Diteruskan ke admin dengan peringatan |
| OCR error atau library belum terpasang | Diteruskan ke admin (alur manual biasa) |

**Kontrol admin** (Panel Admin → Pembayaran)
- **🤖 Auto-Verifikasi ON/OFF**: default OFF. OFF berarti semua bukti diverifikasi manual.
- **🧾 Riwayat Auto**: daftar order yang disetujui bot.
- **🚫 Batalkan Langganan**: pada order Lunas, status order jadi *Dicabut* dan masa VIP dikurangi sebesar hari paket order itu (pembelian sah lain tidak terpengaruh). Jika sisa habis, VIP dinonaktifkan dan session dihentikan. Tersedia opsi **wajib manual** agar pembayaran user tersebut ke depan tidak lagi diverifikasi otomatis.

**Catatan keamanan:** OCR hanya membaca gambar, jadi screenshot hasil editan tetap bisa lolos. Karena itu setiap persetujuan otomatis dilaporkan ke admin, bukti identik dideteksi, dan admin bisa membatalkan kapan saja. Untuk kepastian penuh, cocokkan dengan mutasi rekening.

**Dependensi:** `rapidocr-onnxruntime` (model OCR ikut paket, sekitar 15 MB; RAM 300–500 MB saat OCR berjalan). Jika muncul error `libGL.so.1`, pasang paket sistem `libgl1`.

## 🔑 Token VIP (pindah VIP ke akun lain)

- Setiap pembelian VIP (atau klaim voucher) menerbitkan token acak `RMS-XXXX-XXXX-XXXX` dan menampilkan himbauan untuk menyimpannya di luar akun Telegram.
- Akun baru: menu **🔑 Token VIP → Masukkan Token**. Sisa masa VIP berpindah persis sama, akun lama dinonaktifkan, token ikut berpindah ke akun baru.
- Maksimal **3 kali** pakai. Pembelian VIP periode berikutnya menerbitkan kode baru dan mereset pemakaian ke 0 (kode lama hangus).
- Token hanya bisa dipakai di akun tanpa VIP aktif (trial boleh), dan hanya bila VIP pada token masih aktif.
- Anti tebak-tebak: 6 kode salah dalam 10 menit mengunci input kode (token, voucher, promo) selama 15 menit.
- Admin menerima notifikasi tiap token dipakai. Di kartu user admin tampil token, pemakaian, riwayat pindah, dan tombol **Reset Token**.
- Jika admin membatalkan order lunas yang VIP-nya sudah dipindah lewat token, pembatalan diterapkan ke pemegang VIP saat ini.
- User dengan VIP lama (sebelum fitur ini) atau hasil gift otomatis mendapat token saat membuka menu Token VIP.

## 🏷️ Kode promo (Panel Admin → Kode Promo)

- Diskon 1 sampai 100%. Format buat: `Kode | Persen | Kuota | Berlaku (hari)`, contoh `HEMAT20 | 20 | 50 | 7`. Tulis `acak` pada kode untuk dibuatkan otomatis. Kuota atau masa berlaku 0 atau kosong berarti tanpa batas.
- User memasukkan kode lewat tombol **🏷️ Punya Kode Promo?** di menu Beli VIP. Harga tiap paket langsung tampil terdiskon.
- Satu user hanya bisa memakai satu kode 1 kali. Kuota dihitung dari pesanan aktif atau lunas, pesanan batal atau kedaluwarsa membebaskan kuota.
- Promo 100%: pesanan gratis, tanpa QRIS, VIP langsung aktif dan admin diberi tahu.

## 🎟️ Voucher (Panel Admin → Voucher)

- Buat satuan: `Kode | Hari VIP | Kuota | Berlaku (hari)`, contoh `GRATIS7 | 7 | 10 | 14`.
- **📦 Buat Banyak**: `Hari VIP | Jumlah | Berlaku (hari)` membuat sampai 50 voucher sekali pakai berkode acak.
- User klaim lewat tombol **🎟️ Klaim Voucher** di menu utama. Hari ditambahkan di atas sisa VIP, satu user 1 kali per voucher.
