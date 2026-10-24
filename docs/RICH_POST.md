# 📰 Rich Post

Fitur VIP untuk memposting ke **channel atau grup** memakai [Rich Messages](https://core.telegram.org/bots/api#rich-message-formatting-options) (Bot API 10.1+). Semua berjalan di chat dengan bot, **tanpa session Telethon**.

[← Kembali ke README](../README.md)

**Isi dokumen:** [Mulai cepat](#mulai-cepat) · [Opsi format](#opsi-format) · [Blok tambahan](#blok-tambahan) · [Tombol](#tombol) · [Keamanan](#keamanan-dan-cadangan) · [Catatan teknis](#catatan-teknis)

---

## Mulai cepat

| # | Langkah | Di mana |
|---|---|---|
| 1 | Jadikan bot **admin** di channel atau grup tujuan (di channel, aktifkan izin **Post Messages**) | Telegram |
| 2 | Daftarkan tujuan: kirim `@username`, link `t.me/...`, ID chat (`-100...`), atau **forward** satu pesan dari channel (untuk channel privat) | Bot → Fitur VIP → 📰 Rich Post → **Tujuan Saya** → **Tambah Tujuan** |
| 3 | Kirim isi postingan: teks, atau foto/video dengan caption. Format dasar (tebal, miring, link, kode) ikut dipakai | **Buat Postingan** |
| 4 | Atur opsi dan tambah blok bila perlu | Panel opsi |
| 5 | Cek **Pratinjau** (tampil sebagai Rich Message asli), pilih tujuan, lalu **Posting** | Panel opsi |

**Contoh:** postingan promo = teks pengumuman, judul "Promo Oktober", blok **Daftar** (3 keuntungan), blok **Tabel** (daftar harga), dan tombol **Beli Sekarang** berwarna hijau.

---

## Opsi format

Semua opsi diatur lewat tombol di panel.

| Opsi | Hasil |
|---|---|
| **Gaya** | Normal, Kutipan, Kutipan lipat, Teks lipat, atau Panel (dibungkus `<p>`, `<blockquote>`, `<blockquote expandable>`, `<details>`, `<aside>`) |
| **Judul** | Heading H1 sampai H6 (tombol *Ukuran judul*). Pada gaya *Teks lipat*, judul menjadi ringkasan yang selalu terlihat |
| **Spoiler** | Isi disembunyikan di balik `<tg-spoiler>`. Pada postingan bermedia, foto/video ikut tertutup |
| **Pemisah** | Garis `<hr/>` sebelum footer |
| **Footer** | Teks kecil di bagian bawah |
| **Senyap** | Kirim tanpa notifikasi |
| **Lindungi** | Konten tidak bisa di-forward atau disimpan |
| **Sorot** | Tulis `==teks==` di isi utama menjadi teks disorot (`<mark>`) |

---

## Blok tambahan

Tombol **🧱 Blok** di panel menambah blok setelah isi utama. Bot memandu tiap langkah, jadi tidak perlu hafal sintaks. Blok bisa digeser (⬆️) dan dihapus (🗑️). Maksimal 20 blok.

| Blok | Cara pakai | Hasil |
|---|---|---|
| 🔤 Heading | Pilih ukuran H1/H2/H3, kirim teks | Judul bagian |
| 📋 Daftar | Pilih Poin, Nomor, atau Centang, kirim item satu per baris (`[x]` = sudah dicentang) | `<ul>` / `<ol>`. Centang memakai ☑ dan ☐ |
| 📊 Tabel | Kolom dipisah `\|`, baris pertama jadi header | `<table>` bergaris dan belang, maks 8 kolom, 30 baris |
| 💻 Kode | Pilih bahasa (Python, JavaScript, JSON, Bash, HTML), kirim kodenya | `<pre><code class="language-...">` |
| 💬 Kutipan | `Teks \| Sumber` | `<blockquote>` dengan `<cite>` |
| 📌 Kutipan tengah | `Teks \| Sumber` | `<aside>` dengan `<cite>` |
| 🔽 Teks lipat | Baris pertama = judul, sisanya = isi | `<details>` |
| ➗ Rumus | Kirim LaTeX, contoh `E = mc^2` | `<tg-math-block>` |
| 📍 Peta | Kirim lokasi Telegram atau `-6.2088, 106.8456` | `<tg-map>` |
| 🖼️ Galeri | Pilih Kolase atau Slideshow, kirim 2 sampai 10 foto, tekan Selesai | `<tg-collage>` / `<tg-slideshow>` |
| ➖ Pemisah | Satu ketukan | `<hr/>` |
| 🔘 Tombol | Satu ketukan (tombol harus sudah dibuat) | Menaruh tombol dalam teks tepat di posisi blok |

Input di blok selalu di-escape, jadi karakter seperti `<` aman.

---

## Tombol

Tombol dibuat lewat **🔗 Tombol link**, satu per baris (maks 8):

```
Gabung Channel | https://t.me/namachannel | biru
Buka Website | https://contoh.com
```

Warna (opsional): `biru`, `hijau`, `merah`, `polos`. Hanya tombol URL yang didukung, cocok untuk channel.

### Posisi tombol

| Posisi | Keterangan |
|---|---|
| **Di bawah** (bawaan) | Tombol inline biasa di bawah pesan |
| **Dalam teks** | Tombol Rich Messages (`<tg-button-row>`) yang menjadi bagian isi pesan. Tersedia pengaturan **Kolom** (1 sampai 3 per baris) dan **Rata** (kiri, tengah, kanan) |

Pada mode **Dalam teks**, ada tiga cara menentukan posisi:

1. **Otomatis di akhir isi.** Tidak perlu apa-apa.
2. **Blok 🔘 Tombol.** Satu ketukan di menu Blok, tombol muncul tepat di posisi blok itu.
3. **Penanda di teks.** Tulis di isi postingan, **di baris sendiri**:

   ```
   Promo hari ini!
   {tombol:1}
   Syarat dan ketentuan berlaku.
   {tombol}
   ```

   `{tombol}` menaruh semua tombol, `{tombol:2}` hanya tombol nomor 2. Tombol yang tidak ditunjuk tetap muncul di akhir isi. Pada posisi **Di bawah**, penanda otomatis dibuang dari teks.

Perilaku per gaya: pada *Kutipan* dan *Panel*, tombol ditaruh di luar kutipan. Pada *Teks lipat*, tombol ikut di dalam bagian yang dilipat.

---

## Keamanan dan cadangan

- Posting hanya berjalan jika **bot dan kamu sama-sama admin** di tujuan. Izin dicek ulang tepat sebelum posting, jadi user tidak bisa memposting ke channel orang lain lewat bot ini.
- Jika Telegram menolak Rich Messages, postingan **tidak dikirim otomatis**. Bot menampilkan alasan aslinya dan menawarkan:
  - **Coba dengan tombol biasa** (jika memakai tombol dalam teks).
  - **Kirim sebagai pesan biasa**: format disederhanakan (daftar jadi baris, tabel jadi blok monospace, peta jadi link, gaya lipat dan panel jadi kutipan). Galeri tidak ikut terkirim.
- Daftar tujuan disimpan per user (maks 20) di tabel `rich_targets`.

---

## Catatan teknis

- **Batas:** isi maksimal 32.768 karakter. Rich Messages tampil sempurna di aplikasi Telegram versi terbaru.
- **Klien API:** `python-telegram-bot` 21.11.1 belum mengenal Bot API 10.x, jadi `sendRichMessage` dipanggil lewat HTTP langsung (`utils/rich.py`, memakai `httpx` bawaan dependensi). Ketika library resmi sudah mendukung, klien itu bisa diganti tanpa mengubah alur.
- **Status pengujian:** logika pembangun HTML, parser, klien API, dan alur handler sudah dites (`tests/test_rich.py`). Tag dan atribut Rich HTML (blok, `tg-button`, `style`, `align`) disusun dari dokumentasi Bot API dan spesifikasi pihak ketiga, dan **belum diuji ke server Telegram**. Jika ada yang ditolak, bot menampilkan pesan error asli Telegram, dan perbaikannya cukup di `utils/rich.py`.
- **Kode:** `user/rich_post.py` (menu, draf, posting), `utils/rich.py` (klien, pembangun HTML, validasi blok).
