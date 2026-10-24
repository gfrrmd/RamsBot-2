"""
Baca bukti transfer (screenshot) dengan OCR lalu cocokkan dengan order.

Aturan verifikasi:
  - WAJIB : nominal pada gambar sama persis dengan total order (termasuk kode unik).
  - OPSIONAL : tanggal & jam transaksi. Jika terbaca, harus berada di rentang
    "order dibuat" s/d "batas waktu bayar". Jika tidak terbaca, hanya nominal yang dicek.

Mesin OCR: RapidOCR (onnxruntime) — offline, gratis, tanpa API key. Perbandingan nominal
dilakukan di kode (bukan oleh model), sehingga teks di dalam gambar tidak bisa
"menyuruh" bot menyetujui pembayaran.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

# Toleransi selisih jam server vs jam bank (menit) di kedua ujung rentang waktu.
TIME_TOLERANCE = timedelta(minutes=3)
MAX_SIDE = 2600          # perkecil gambar yang terlalu besar (kecepatan OCR)
MIN_SIDE = 900           # perbesar gambar kecil (akurasi OCR)

_engine = None
_engine_lock = threading.Lock()
_ocr_sem: asyncio.Semaphore | None = None


class ReceiptError(Exception):
    pass


@dataclass
class ReceiptResult:
    # match | amount_mismatch | time_mismatch | unreadable | error
    status: str
    expected: int = 0
    amounts: list[int] = field(default_factory=list)
    paid_at_wib: datetime | None = None
    time_checked: str = "none"          # datetime | date | none
    note: str = ""
    rows: list[str] = field(default_factory=list)


# ── Mesin OCR ─────────────────────────────────────────────────────────────────

_ocr_error = ""


def ocr_available() -> bool:
    """True jika library OCR bisa di-import. Penyebab kegagalan disimpan di ocr_error()."""
    global _ocr_error
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
        _ocr_error = ""
        return True
    except Exception as e:
        _ocr_error = f"{type(e).__name__}: {e}"[:180]
        return False


def ocr_error() -> str:
    return _ocr_error


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        return _engine


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _group_rows(items: list) -> list[str]:
    """Kelompokkan hasil OCR (box, teks, skor) menjadi baris teks berurutan atas→bawah, kiri→kanan."""
    boxes = []
    for it in items:
        try:
            box, text = it[0], str(it[1]).strip()
        except Exception:
            continue
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append({"x": min(xs), "cy": (min(ys) + max(ys)) / 2, "h": max(ys) - min(ys), "t": text})
    if not boxes:
        return []
    boxes.sort(key=lambda b: b["cy"])
    heights = sorted(b["h"] for b in boxes)
    tol = max(6.0, 0.6 * heights[len(heights) // 2])
    rows: list[list[dict]] = []
    for b in boxes:
        if rows and abs(rows[-1][-1]["cy"] - b["cy"]) <= tol:
            rows[-1].append(b)
        else:
            rows.append([b])
    out = []
    for r in rows:
        r.sort(key=lambda b: b["x"])
        out.append(" ".join(b["t"] for b in r))
    return out


def ocr_rows(data: bytes) -> list[str]:
    """Jalankan OCR pada bytes gambar → daftar baris teks. Blocking (panggil via thread)."""
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ReceiptError("Gambar tidak dapat dibuka.")
    h, w = img.shape[:2]
    side = max(h, w)
    if side > MAX_SIDE:
        s = MAX_SIDE / side
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    elif side < MIN_SIDE:
        s = MIN_SIDE / side
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC)
    result, _ = _get_engine()(img)
    return _group_rows(result or [])


# ── Parser nominal ────────────────────────────────────────────────────────────

_CUR_RE = re.compile(r"(?i)\b(?:rp|idr)\b\.?\s*([0-9OolIS][0-9OolIS.,]*)")
_NUM_RE = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d{3,9}(?:[.,]\d{1,2})?)(?![\d])")
_KEYWORD_RE = re.compile(r"(?i)nominal|jumlah|total|transfer|bayar|amount|tagihan|pembayaran|dibayar|harga")
_OCR_DIGIT = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "S": "5"})


def _to_int(token: str) -> int | None:
    """'25.012' / '25,012.00' / '25.012,00' / '25012,00' / '25012' → bilangan bulat rupiah."""
    t = token.strip(".,")
    if not t or not re.fullmatch(r"[\d.,]+", t):
        return None
    m = re.fullmatch(r"(.+?)[.,](\d{1,2})", t)          # pemisah terakhir + 1–2 digit = desimal → buang
    if m:
        t = m.group(1)
    digits = re.sub(r"[.,]", "", t)
    if not digits.isdigit():
        return None
    v = int(digits)
    return v if 0 < v < 10**10 else None


def extract_amounts(rows: list[str]) -> tuple[list[int], list[int]]:
    """
    Return (kandidat_kuat, semua_kandidat).
    Kuat   = diawali Rp/IDR, atau ada pemisah ribuan, atau satu baris dengan kata kunci (nominal/total/...).
    """
    strong: list[int] = []
    weak: list[int] = []
    for row in rows:
        has_kw = bool(_KEYWORD_RE.search(row))
        cur_spans = []
        for m in _CUR_RE.finditer(row):
            tok = m.group(1).translate(_OCR_DIGIT)
            v = _to_int(tok)
            if v is not None:
                strong.append(v)
                cur_spans.append(m.span(1))
        for m in _NUM_RE.finditer(row):
            if any(s <= m.start() < e for s, e in cur_spans):
                continue
            tok = m.group(1)
            v = _to_int(tok)
            if v is None:
                continue
            if re.search(r"[.,]\d{3}", tok) or has_kw:
                strong.append(v)
            else:
                weak.append(v)
    return strong, strong + weak


# ── Parser tanggal & jam ──────────────────────────────────────────────────────

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6, "jul": 7,
    "agu": 8, "agt": 8, "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "des": 12, "dec": 12,
}
_DATE_TXT = re.compile(r"(?i)\b(\d{1,2})[\s/\-.]*(jan|feb|mar|apr|mei|may|jun|jul|agu|agt|aug|sep|okt|oct|nov|des|dec)[a-z]*\.?[\s/\-.,]*(\d{4}|\d{2})\b")
_DATE_NUM = re.compile(r"(?<![\d])(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?![\d])")
_DATE_ISO = re.compile(r"(?<![\d])(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?![\d])")
_TIME_RE = re.compile(r"(?<![\d.,:])([01]?\d|2[0-3])[:.]([0-5]\d)(?:[:.]([0-5]\d))?(?![\d])")
_TZ_RE = re.compile(r"(?i)\b(WIB|WITA|WIT)\b")
_TZ_OFFSET = {"WIB": 7, "WITA": 8, "WIT": 9}


def _year(y: str) -> int:
    n = int(y)
    return 2000 + n if n < 100 else n


def _find_date(row: str) -> tuple[date, tuple[int, int]] | None:
    for rx, order in ((_DATE_ISO, "ymd"), (_DATE_TXT, "dmy_txt"), (_DATE_NUM, "dmy")):
        m = rx.search(row)
        if not m:
            continue
        try:
            if order == "ymd":
                d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            elif order == "dmy_txt":
                d = date(_year(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
            else:
                d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except (ValueError, KeyError):
            continue
        return d, m.span()
    return None


def extract_datetimes(rows: list[str], default_offset: int = 7) -> list[tuple[datetime, bool, int]]:
    """
    Return [(datetime_lokal_naive, punya_jam, offset_jam)].
    Jam hanya dipakai jika berada pada baris yang SAMA dengan tanggal (atau baris persis
    di bawahnya), supaya jam di status bar HP (waktu screenshot) tidak ikut terbaca.
    """
    found: list[tuple[datetime, bool, int]] = []
    for i, row in enumerate(rows):
        hit = _find_date(row)
        if not hit:
            continue
        d, (_, end) = hit
        offset = default_offset
        tzm = _TZ_RE.search(row)
        scope = row[end:]
        tm = None
        for m in _TIME_RE.finditer(scope):
            sep_is_dot = "." in m.group(0)
            if sep_is_dot and not (_TZ_RE.search(scope[m.end():m.end() + 8]) or tzm):
                continue                     # 14.32 tanpa 'WIB' terlalu ambigu (bisa angka lain)
            tm = m
            break
        if tm is None and i + 1 < len(rows) and not _find_date(rows[i + 1]):
            nxt = rows[i + 1]
            m2 = _TIME_RE.search(nxt)
            if m2 and ":" in m2.group(0) and len(nxt) <= 24:
                tm = m2
                tzm = tzm or _TZ_RE.search(nxt)
        if tzm:
            offset = _TZ_OFFSET[tzm.group(1).upper()]
        if tm:
            hh, mm = int(tm.group(1)), int(tm.group(2))
            ss = int(tm.group(3)) if tm.group(3) else 0
            found.append((datetime(d.year, d.month, d.day, hh, mm, ss), True, offset))
        else:
            found.append((datetime(d.year, d.month, d.day), False, offset))
    return found


# ── Verifikasi ────────────────────────────────────────────────────────────────

def _fmt_wib(dt: datetime, has_time: bool) -> str:
    return f"{dt:%d-%m-%Y %H:%M}" if has_time else f"{dt:%d-%m-%Y}"


def evaluate(rows: list[str], expected_total: int, created_utc: datetime, deadline_utc: datetime,
             default_offset: int = 7) -> ReceiptResult:
    """Murni logika (tanpa OCR) — mudah diuji. created_utc/deadline_utc = datetime naive UTC."""
    res = ReceiptResult(status="unreadable", expected=expected_total, rows=rows)
    if not rows:
        res.note = "Tidak ada teks yang terbaca pada gambar."
        return res

    strong, every = extract_amounts(rows)
    res.amounts = sorted(set(strong or every))[:8]
    if not every:
        res.note = "Tidak ada nominal yang terbaca."
        return res
    if expected_total not in strong:
        res.status = "amount_mismatch"
        seen = ", ".join(f"{a:,}".replace(",", ".") for a in res.amounts) or "-"
        res.note = f"Nominal pada gambar tidak sama dengan total order. Terbaca: {seen}."
        return res

    # Nominal cocok → cek waktu (opsional)
    dts = extract_datetimes(rows, default_offset)
    if not dts:
        res.status, res.time_checked = "match", "none"
        res.note = "Nominal cocok. Tanggal/jam tidak terbaca → hanya nominal yang diverifikasi."
        return res

    lo, hi = created_utc - TIME_TOLERANCE, deadline_utc + TIME_TOLERANCE
    best: tuple[datetime, bool] | None = None
    for dt, has_time, off in dts:
        utc = dt - timedelta(hours=off)
        wib = dt + timedelta(hours=7 - off)
        if has_time:
            ok = lo <= utc <= hi
        else:
            ok = (lo + timedelta(hours=off)).date() <= dt.date() <= (hi + timedelta(hours=off)).date()
        if ok:
            res.status = "match"
            res.paid_at_wib = wib
            res.time_checked = "datetime" if has_time else "date"
            res.note = f"Nominal & waktu cocok ({_fmt_wib(wib, has_time)} WIB)."
            return res
        best = best or (wib, has_time)

    res.status = "time_mismatch"
    res.paid_at_wib = best[0]
    res.time_checked = "datetime" if best[1] else "date"
    res.note = (f"Nominal cocok, tetapi waktu pada bukti ({_fmt_wib(best[0], best[1])} WIB) "
                "di luar rentang pembayaran order.")
    return res


async def verify_receipt(data: bytes, expected_total: int, created_utc: datetime, deadline_utc: datetime,
                         default_offset: int = 7) -> ReceiptResult:
    """OCR di thread terpisah (maks 1 proses OCR sekaligus agar RAM aman) lalu evaluasi."""
    global _ocr_sem
    if _ocr_sem is None:
        _ocr_sem = asyncio.Semaphore(1)
    try:
        async with _ocr_sem:
            rows = await asyncio.wait_for(asyncio.to_thread(ocr_rows, data), timeout=60)
    except Exception as e:                                  # engine belum terpasang / gagal / timeout
        return ReceiptResult(status="error", expected=expected_total, note=f"OCR gagal: {type(e).__name__}: {e}"[:200])
    return evaluate(rows, expected_total, created_utc, deadline_utc, default_offset)
