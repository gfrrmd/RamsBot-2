# 📰 Rich Post

Fitur VIP untuk memposting ke **channel atau grup** memakai [Rich Messages](https://core.telegram.org/bots/api#rich-message-formatting-options) (Bot API 10.1+). Semua berjalan di chat dengan bot, **tanpa session Telethon**.

[← Kembali ke README](../README.md)

**Isi dokumen:** [Mulai cepat](#mulai-cepat) · [Menu panel](#menu-panel) · [Opsi tampilan](#opsi-tampilan) · [Blok dan urutan](#blok-dan-urutan) · [Tombol](#tombol) · [Keamanan](#keamanan-dan-cadangan) · [Catatan teknis](#catatan-teknis)

---

## Mulai cepat

| # | Langkah | Di mana |
|---|---|---|
| 1 | Jadikan bot **admin** di channel atau grup tujuan (di channel, aktifkan izin **Post Messages**) | Telegram |
| 2 | Daftarkan tujuan: kirim `@username`, link `t.me/...`, ID chat (`-100...`), atau **forward** satu pesan dari channel (untuk channel privat) | Bot → Fitur VIP → 📰 Rich Post → **Tujuan Saya** → **Tambah Tujuan** |
| 3 | Kirim isi postingan: teks, atau foto/video dengan caption. Format dasar (tebal, miring, link, kode) ikut dipakai | **Buat Postingan** |
| 4 | Atur lewat kategori: 🎨 Tampilan, 🧱 Blok & Urutan, 🔘 Tombol, ⚙️ Pengiriman | Panel opsi |
| 5 | Cek **Pratinjau** (tampil sebagai Rich Message asli), pilih tujuan, lalu **Posting** | Panel opsi |

**Contoh:** postingan promo = teks pengumuman, judul "Promo Oktober", blok **Daftar** (3 keuntungan), blok **Tabel** (daftar harga), tombol **Beli Sekarang** (hijau), **Salin Kode** dan **Bagikan** sebaris.

---

## Menu panel

Panel dibagi per kategori supaya tidak penuh tombol:

| Kategori | Isi |
|---|---|
| 🎨 **Tampilan** | Gaya, spoiler, pemisah, judul, ukuran judul, footer |
| 🧱 **Blok & Urutan** | Susunan isi (geser ⬆️⬇️, hapus 🗑), tambah blok per kategori |
| 🔘 **Tombol** | Tambah tombol per jenis, atur baris, posisi, rata |
| ⚙️ **Pengiriman** | Senyap, lindungi |

---

## Opsi tampilan

| Opsi | Hasil |
|---|---|
| **Gaya** | Normal, Kutipan, Kutipan lipat, Teks lipat, atau Panel (dibungkus `<p>`, `<blockquote>`, `<blockquote expandable>`, `<details>`, `<aside>`) |
| **Judul** | Heading H1 sampai H6 (tombol *Ukuran judul*). Pada gaya *Teks lipat*, judul menjadi ringkasan yang selalu terlihat |
| **Spoiler** | Teks dan foto/video utama disembunyikan di balik `<tg-spoiler>` |
| **Pemisah** | Garis `<hr/>` sebelum footer |
| **Footer** | Teks kecil di bagian bawah |
| **Senyap** / **Lindungi** | Tanpa notifikasi / tidak bisa di-forward atau disimpan |
| **Sorot** | Tulis `==teks==` di isi utama menjadi teks disorot (`<mark>`) |

---

## Blok dan urutan

Menu **🧱 Blok & Urutan** menampilkan susunan isi dari atas ke bawah. **📝 Teks utama** (judul + isi) dan **🖼 Media utama** (foto/video pertama) ikut ada di daftar dan bisa **dipindah dengan ⬆️⬇️**. Contoh: taruh tabel di atas teks, atau media di paling bawah. Teks utama dan media utama tidak bisa dihapus (ganti lewat ✏️ Ganti Isi). Blok tambahan maksimal 20.

**➕ Tambah Blok** dikelompokkan:

| Kategori | Blok |
|---|---|
| 📝 Teks | Heading, Kutipan, Kutipan tengah, Teks lipat, Pemisah |
| 📊 Data | Daftar, Tabel, Kode, Rumus |
| 🖼 Media & File | Galeri, **Musik**, **Berkas**, Peta |
| 🔘 Tombol | Menaruh tombol tepat di posisi blok |

| Blok | Cara pakai | Hasil |
|---|---|---|
| 🔤 Heading | Pilih ukuran H1/H2/H3, kirim teks | Judul bagian |
| 📋 Daftar | Pilih Poin, Nomor, atau Centang, kirim item satu per baris (`[x]` = dicentang) | `<ul>` / `<ol>` |
| 📊 Tabel | Kolom dipisah `\|`, baris pertama jadi header | `<table>` maks 8 kolom, 30 baris |
| 💻 Kode | Pilih bahasa, kirim kodenya | `<pre><code class="language-...">` |
| 💬 Kutipan / 📌 Kutipan tengah | `Teks \| Sumber` | `<blockquote>` / `<aside>` dengan `<cite>` |
| 🔽 Teks lipat | Baris pertama = judul, sisanya = isi | `<details>` |
| ➗ Rumus | Kirim LaTeX, contoh `E = mc^2` | `<tg-math-block>` |
| 📍 Peta | Lokasi Telegram atau `-6.2088, 106.8456` | `<tg-map>` |
| 🖼️ Galeri | Pilih Kolase atau Slideshow, kirim 2 sampai 10 foto, atur **🙈 Spoiler**, tekan Selesai | `<tg-collage>` / `<tg-slideshow>`; spoiler memberi `tg-spoiler` pada tiap foto |
| 🎵 Musik | Kirim file sebagai **Audio** atau pesan suara. Caption jadi keterangan | `<audio src="tg://audio?id=...">` |
| 📎 Berkas | Kirim file sebagai **Dokumen** (PDF, ZIP, dll). Caption jadi keterangan | `<tg-document src="tg://document?id=...">` |
| ➖ Pemisah | Satu ketukan | `<hr/>` |
| 🔘 Tombol | Satu ketukan (tombol harus sudah dibuat) | Tombol dalam teks tepat di posisi blok |

Spoiler galeri juga bisa diubah kapan saja lewat tombol 🙈 di baris galeri pada daftar susunan.

Input di blok selalu di-escape, jadi karakter seperti `<` aman.

---

## Tombol

Menu **🔘 Tombol** punya enam jenis. Pilih jenis, lalu kirim tombolnya:

| Jenis | Fungsi | Contoh input |
|---|---|---|
| 🔗 **Link** | Membuka link | `Beli | https://toko.id` |
| 📋 **Salin** | Menyalin teks ke clipboard (kode promo, rekening) | `Salin Kode | PROMO50` |
| 📤 **Bagikan** | Membuka daftar chat untuk membagikan link | `Bagikan | https://t.me/channel` |
| 💬 **Chat** | Membuka chat akun/channel/bot | `Hubungi | @username` |
| 💡 **Popup** | Memunculkan jendela info (maks 200 karakter) | `Info | Berlaku sampai Jumat` |
| 👍 **Vote** | Tombol reaksi dengan hitungan; satu orang satu suara, menekan lagi membatalkan | `👍 Suka && 👎 Tidak` |

Aturan input:

- **Satu baris = satu baris tombol.** Beberapa tombol **sebaris**: pisahkan dengan `&&`, misalnya `Salin | PROMO50 && Bagikan | https://t.me/channel`.
- Warna (opsional) di akhir: `| biru`, `| hijau`, `| merah`, `| polos`.
- **✍️ Tulis Sekaligus** menerima banyak tombol campuran dengan awalan jenis (`salin:`, `bagikan:`, `chat:`, `popup:`, atau `vote`) dan **menggantikan** semua tombol lama:

```
Beli Sekarang | https://contoh.com | hijau
Salin Kode | salin: PROMO50 && Bagikan | bagikan: https://t.me/channel
Info | popup: Berlaku sampai Jumat
👍 Suka && 👎 Tidak | vote
```

- **🧩 Atur Baris**: geser tombol (⬆️), gabung ke baris atas atau pisah (↔️ / ⤵️), hapus (🗑), atau susun otomatis **1/2/3 per baris**. Maksimal 12 tombol, 8 per baris.

### Posisi tombol

| Posisi | Keterangan |
|---|---|
| **Di bawah** (bawaan) | Tombol inline biasa di bawah pesan. Semua jenis didukung |
| **Dalam teks** | Tombol Rich Messages yang menjadi bagian isi (`<tg-button-row>`), dengan pengaturan **Rata** (kiri, tengah, kanan). Mendukung Link, Bagikan, Chat, dan Popup. **Salin dan Vote tetap tampil di bawah pesan** |

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

   `{tombol}` menaruh semua tombol, `{tombol:2}` hanya tombol nomor 2 (nomor sesuai daftar di menu Tombol). Tombol yang tidak ditunjuk tetap muncul di akhir isi. Pada posisi **Di bawah**, penanda otomatis dibuang.

Perilaku per gaya: pada *Kutipan* dan *Panel*, tombol ditaruh di luar kutipan. Pada *Teks lipat*, tombol ikut di dalam bagian yang dilipat.

### Cara kerja Popup dan Vote

- Teks popup dan hitungan vote disimpan di database lokal (tabel `rich_popups`, `rich_polls`, `rich_votes`), jadi tetap jalan setelah bot restart. Popup dan vote bisa ditekan **siapa saja** di channel/grup, bukan hanya VIP.
- Bot harus tetap aktif agar tombol Popup dan Vote merespons.
- Pada **Pratinjau**, Popup dan Vote hanya menampilkan pemberitahuan pratinjau. Fungsinya aktif setelah diposting.

---

## Keamanan dan cadangan

- Posting hanya berjalan jika **bot dan kamu sama-sama admin** di tujuan. Izin dicek ulang tepat sebelum posting, jadi user tidak bisa memposting ke channel orang lain lewat bot ini.
- Jika Telegram menolak Rich Messages, postingan **tidak dikirim otomatis**. Bot menampilkan alasan aslinya dan menawarkan:
  - **Coba dengan tombol di bawah** (jika memakai tombol dalam teks).
  - **Kirim sebagai pesan biasa**: format disederhanakan (daftar jadi baris, tabel jadi blok monospace, peta jadi link, gaya lipat dan panel jadi kutipan). Galeri, musik, dan berkas dikirim sebagai pesan terpisah, semua tombol (termasuk Salin, Popup, Vote) tetap ada.
- Daftar tujuan disimpan per user (maks 20) di tabel `rich_targets`.

---

## Catatan teknis

- **Batas:** isi maksimal 32.768 karakter. Rich Messages tampil sempurna di aplikasi Telegram versi terbaru.
- **Klien API:** `python-telegram-bot` 21.11.1 belum mengenal Bot API 10.x, jadi `sendRichMessage` dipanggil lewat HTTP langsung (`utils/rich.py`, memakai `httpx` bawaan dependensi). Ketika library resmi sudah mendukung, klien itu bisa diganti tanpa mengubah alur.
- **Status pengujian:** logika pembangun HTML, parser, klien API, dan alur menu sudah dites (`tests/test_rich.py`). Yang **belum diuji ke server Telegram**: tag `<tg-document>` untuk Berkas (nama tag tercantum di dokumentasi Bot API 10.3, atribut `src="tg://document?id=..."` mengikuti pola media lain), atribut `tg-spoiler` pada foto di dalam galeri, dan tombol Popup dalam teks (`<tg-button type="callback_data" data="...">`). Jika ada yang ditolak, bot menampilkan pesan error asli Telegram dan menawarkan kirim sebagai pesan biasa; perbaikannya cukup di `utils/rich.py`.
- **Kode:** `user/rich_post.py` (menu, draf, posting, tombol popup/vote), `utils/rich.py` (klien, pembangun HTML, parser tombol, validasi blok).
