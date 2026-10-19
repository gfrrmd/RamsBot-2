import sys; sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__file__), '..'))
from datetime import datetime, timedelta
from utils.receipt import evaluate, _to_int

assert _to_int("25.012")==25012
assert _to_int("25,012.00")==25012
assert _to_int("25.012,00")==25012
assert _to_int("25012,00")==25012
assert _to_int("25012")==25012
assert _to_int("1.250.000")==1250000

# order dibuat 19 Okt 2026 10:00 WIB = 03:00 UTC, batas 60 menit
created = datetime(2026,10,19,3,0,0); deadline = created+timedelta(minutes=60)
T=25012
def ev(rows): return evaluate(rows,T,created,deadline)

# 1 nominal + waktu cocok (WIB)
r=ev(["Transfer Berhasil","19 Okt 2026, 10:25:41 WIB","Nominal Rp 25.012","Biaya admin Rp 0"]); print(1,r.status,r.note); assert r.status=="match" and r.time_checked=="datetime"
# 2 waktu setelah batas (11:30 WIB) -> time_mismatch
r=ev(["19 Okt 2026 11:30","Rp 25.012"]); print(2,r.status,r.note); assert r.status=="time_mismatch"
# 3 tanggal kemarin -> mismatch (bukti lama dipakai ulang)
r=ev(["18 Okt 2026 10:25","Rp 25.012"]); print(3,r.status); assert r.status=="time_mismatch"
# 4 tanpa tanggal/jam, hanya nominal -> match
r=ev(["Pembayaran berhasil","Total Rp25.012"]); print(4,r.status,r.time_checked); assert r.status=="match" and r.time_checked=="none"
# 5 jam status bar HP saja (tidak sebaris tanggal) -> diabaikan
r=ev(["14:02","Transfer berhasil","Rp 25.012"]); print(5,r.status,r.time_checked); assert r.status=="match" and r.time_checked=="none"
# 6 nominal salah (tanpa kode unik)
r=ev(["19 Okt 2026 10:20","Rp 25.000"]); print(6,r.status,r.note); assert r.status=="amount_mismatch"
# 7 tanggal saja, hari sama
r=ev(["Tanggal 19/10/2026","Jumlah 25.012,00"]); print(7,r.status,r.time_checked); assert r.status=="match" and r.time_checked=="date"
# 8 format dot jam + WIB, ISO date
r=ev(["2026-10-19 10.30 WIB","IDR 25,012.00"]); print(8,r.status,r.time_checked); assert r.status=="match"
# 9 OCR salah baca O/l di nominal
r=ev(["Rp 25.O12"]); print(9,r.status); assert r.status=="match"
# 10 teks kosong
r=ev([]); print(10,r.status); assert r.status=="unreadable"
# 11 jam di baris bawah tanggal
r=ev(["Tanggal","19 Oktober 2026","10:40 WIB","Rp 25.012"]); print(11,r.status,r.time_checked); assert r.status=="match" and r.time_checked=="datetime"
# 12 WITA: 11:25 WITA = 10:25 WIB -> cocok
r=ev(["19 Okt 2026 11:25 WITA","Rp 25.012"]); print(12,r.status); assert r.status=="match"
# 13 nomor referensi panjang yang kebetulan memuat 25012 tidak dianggap nominal
r=ev(["No. Ref 9025012345","Rp 30.000"]); print(13,r.status); assert r.status=="amount_mismatch"
# 14 angka polos 25012 tanpa Rp/pemisah/kata kunci -> tidak cukup kuat
r=ev(["ID 25012"]); print(14,r.status); assert r.status=="amount_mismatch"
print("ALL OK")
