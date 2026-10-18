"""
Inti fitur QRIS: konversi QRIS statis -> dinamis.

Port dari project `qris-dinamis` (TypeScript) ke Python, ditambah:
  - decode gambar QR (zxing-cpp, fallback OpenCV)
  - render gambar QR dinamis (PNG) siap kirim
  - parser nominal ala chat Indonesia (25000, 25.000, 25k, 25rb, 1jt)
"""
from __future__ import annotations

import io
import re

MAX_AMOUNT = 999_999_999
MIN_AMOUNT = 1


class QRISError(ValueError):
    """Error yang pesannya aman ditampilkan ke user."""


# ── CRC16 / TLV ───────────────────────────────────────────────────────────────

def crc16(data: str) -> str:
    """CRC16-CCITT (poly 0x1021, init 0xFFFF) — standar EMVCo/QRIS."""
    crc = 0xFFFF
    for ch in data:
        crc ^= ord(ch) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc & 0xFFFF:04X}"


def parse_tlv(data: str) -> list[tuple[str, str]]:
    """Parse TLV level atas -> [(tag, value), ...]. Berhenti jika struktur rusak."""
    out: list[tuple[str, str]] = []
    pos = 0
    while pos + 4 <= len(data):
        tag = data[pos:pos + 2]
        len_str = data[pos + 2:pos + 4]
        if not len_str.isdigit():
            break
        length = int(len_str)
        if pos + 4 + length > len(data):
            break
        out.append((tag, data[pos + 4:pos + 4 + length]))
        pos += 4 + length
    return out


def _build_tlv(elements: list[tuple[str, str]]) -> str:
    return "".join(f"{tag}{len(value):02d}{value}" for tag, value in elements)


# ── Validasi ──────────────────────────────────────────────────────────────────

_REQUIRED_TAGS = {
    "00": "Payload Format Indicator",
    "01": "Point of Initiation Method",
    "52": "Merchant Category Code",
    "53": "Transaction Currency",
    "58": "Country Code",
    "59": "Merchant Name",
    "60": "Merchant City",
    "63": "CRC",
}


def validate_qris(qris: str) -> list[str]:
    """Kembalikan daftar error. List kosong = valid."""
    s = (qris or "").strip()
    if not s:
        return ["Data QRIS kosong"]
    errors: list[str] = []
    if not s.startswith("000201"):
        errors.append("Bukan format QRIS (harus diawali 000201)")
    if len(s) < 20:
        return errors + ["Data QRIS terlalu pendek"]
    declared = s[-4:].upper()
    calculated = crc16(s[:-4])
    if declared != calculated:
        errors.append("CRC tidak cocok — data QRIS rusak atau terpotong")
    elements = parse_tlv(s)
    if not elements:
        return errors + ["Struktur QRIS tidak bisa dibaca"]
    tags = {t for t, _ in elements}
    for tag, name in _REQUIRED_TAGS.items():
        if tag not in tags:
            errors.append(f"Tag wajib {tag} ({name}) tidak ada")
    method = dict(elements).get("01")
    if method is not None and method not in ("11", "12"):
        errors.append(f"Point of Initiation tidak valid: {method}")
    if not any(26 <= int(t) <= 51 for t, _ in elements if t.isdigit()):
        errors.append("Merchant Account Information (tag 26-51) tidak ada")
    return errors


def summarize_qris(qris: str) -> dict:
    """Ringkasan untuk ditampilkan: nama merchant, kota, tipe."""
    d = dict(parse_tlv(qris.strip()))
    return {
        "merchant_name": d.get("59", "").strip(),
        "merchant_city": d.get("60", "").strip(),
        "method": "dynamic" if d.get("01") == "12" else "static",
    }


# ── Konversi statis -> dinamis ────────────────────────────────────────────────

def convert_qris(static_qris: str, amount: int, fee: tuple[str, int] | None = None) -> str:
    """
    Ubah QRIS statis menjadi dinamis dengan menyisipkan nominal (tag 54).

    fee: opsional ("fixed"|"percentage", nilai) -> tag 55 + 56/57.
    Langkah sama dengan converter TypeScript: tag 01 -> "12", tag 54 disisipkan
    sebelum tag 58, tag 54/55/56/57/63 lama dibuang, lalu hitung ulang CRC16.
    """
    if not isinstance(amount, int) or amount < MIN_AMOUNT:
        raise QRISError("Nominal tidak valid")
    if amount > MAX_AMOUNT:
        raise QRISError(f"Nominal terlalu besar (maksimal {MAX_AMOUNT:,})".replace(",", "."))
    elements = parse_tlv(static_qris.strip())
    if not elements:
        raise QRISError("Struktur QRIS tidak bisa dibaca")

    managed = {"54", "55", "56", "57", "63"}
    result: list[tuple[str, str]] = []
    inserted = False
    for tag, value in elements:
        if tag in managed:
            continue
        if tag == "01":
            result.append(("01", "12"))
            continue
        if tag == "58" and not inserted:
            result.append(("54", str(amount)))
            if fee:
                kind, fee_val = fee
                if kind == "fixed":
                    result += [("55", "02"), ("56", str(fee_val))]
                else:
                    result += [("55", "03"), ("57", str(fee_val))]
            inserted = True
        result.append((tag, value))
    if not inserted:
        raise QRISError("QRIS tidak memiliki tag Country Code (58)")

    body = _build_tlv(result) + "6304"
    return body + crc16(body)


# ── Parser nominal ────────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(r"^(?:rp\.?\s*)?([\d.,]+)\s*(k|rb|ribu|jt|juta)?$", re.IGNORECASE)
_THOUSANDS_RE = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
_MULT = {"k": 1_000, "rb": 1_000, "ribu": 1_000, "jt": 1_000_000, "juta": 1_000_000}


def parse_amount(text: str) -> int | None:
    """
    '25000' '25.000' 'Rp 25.000' '25k' '25rb' '1jt' '1,5jt' -> int rupiah.
    Return None jika tidak bisa dibaca.
    """
    t = (text or "").strip().lower().replace(" ", "")
    if not t:
        return None
    m = _AMOUNT_RE.match(t)
    if not m:
        return None
    num, suffix = m.group(1), m.group(2)
    if suffix:
        try:
            val = float(num.replace(",", "."))
        except ValueError:
            return None
        amount = round(val * _MULT[suffix.lower()])
    else:
        if _THOUSANDS_RE.match(num):
            num = re.sub(r"[.,]", "", num)
        if not num.isdigit():
            return None
        amount = int(num)
    return amount if amount >= MIN_AMOUNT else None


def format_rupiah(n: int) -> str:
    return "Rp " + f"{int(n):,}".replace(",", ".")


# ── Decode gambar QR -> string QRIS ───────────────────────────────────────────

def _image_variants(img):
    """Beberapa varian gambar untuk meningkatkan peluang decode QR yang padat."""
    from PIL import Image, ImageOps

    base = img.convert("RGB")
    w, h = base.size
    longest = max(w, h)
    if longest > 2000:                      # foto kamera resolusi besar
        scale = 1600 / longest
        base = base.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    yield base
    gray = ImageOps.autocontrast(base.convert("L"))
    yield gray
    padded = ImageOps.expand(gray, border=max(40, gray.size[0] // 12), fill=255)
    yield padded
    if max(gray.size) < 900:                # screenshot kecil -> perbesar
        yield gray.resize((gray.size[0] * 2, gray.size[1] * 2), Image.LANCZOS)
    yield gray.point(lambda p: 255 if p > 140 else 0)


def _pick(texts: list[str]) -> str | None:
    for t in texts:
        if t and t.strip().startswith("0002"):
            return t.strip()
    return None


def decode_qr_image(data: bytes) -> str | None:
    """Baca isi QR dari bytes gambar. None jika tidak ada QRIS yang terbaca."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None

    variants = list(_image_variants(img))

    try:  # 1) zxing-cpp — paling andal untuk QR padat
        import zxingcpp
        for v in variants:
            found = _pick([r.text for r in zxingcpp.read_barcodes(v)])
            if found:
                return found
    except ImportError:
        pass
    except Exception:
        pass

    try:  # 2) fallback OpenCV
        import cv2
        import numpy as np
        detectors = [cv2.QRCodeDetector()]
        if hasattr(cv2, "QRCodeDetectorAruco"):
            detectors.append(cv2.QRCodeDetectorAruco())
        for v in variants:
            arr = np.array(v.convert("L"))
            for det in detectors:
                try:
                    text, _, _ = det.detectAndDecode(arr)
                except Exception:
                    continue
                found = _pick([text])
                if found:
                    return found
    except ImportError:
        pass
    return None


def extract_qris_from_text(text: str) -> str | None:
    """Terima QRIS yang ditempel sebagai teks mentah."""
    # Hanya buang line break (teks hasil copy sering terpotong baris). Spasi di
    # dalam payload TIDAK boleh dibuang: nama merchant bisa mengandung spasi.
    t = re.sub(r"[\r\n]+", "", (text or "").strip())
    return t if t.startswith("000201") else None


# ── Render QR dinamis -> PNG ──────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)   # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def _qr_matrix(payload: str) -> list[list[bool]]:
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=1, border=0)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.get_matrix()


def render_qr_png(payload: str, title: str = "QRIS", merchant: str = "", amount: int | None = None) -> bytes:
    """Gambar kartu QR: judul, QR (quiet zone luas), nama merchant & nominal."""
    from PIL import Image, ImageDraw

    matrix = _qr_matrix(payload)
    n = len(matrix)
    box = max(4, 560 // n)
    qr_px = n * box
    quiet = max(40, box * 4)                 # quiet zone standar QR = 4 modul
    band_h = 70
    width = max(qr_px + quiet * 2, 520)
    footer_h = 130 if (merchant or amount) else 40
    height = band_h + quiet + qr_px + footer_h

    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, width, band_h], fill=(200, 16, 46))
    f_title = _load_font(34, bold=True)
    tw = d.textlength(title, font=f_title)
    d.text(((width - tw) / 2, 18), title, font=f_title, fill="white")

    ox = (width - qr_px) // 2
    oy = band_h + quiet
    for y, row in enumerate(matrix):
        for x, cell in enumerate(row):
            if cell:
                d.rectangle([ox + x * box, oy + y * box, ox + (x + 1) * box - 1, oy + (y + 1) * box - 1], fill="black")

    ty = oy + qr_px + 14
    if merchant:
        f_m = _load_font(24, bold=True)
        name = merchant[:34]
        mw = d.textlength(name, font=f_m)
        d.text(((width - mw) / 2, ty), name, font=f_m, fill=(30, 30, 30))
        ty += 40
    if amount:
        f_a = _load_font(36, bold=True)
        txt = format_rupiah(amount)
        aw = d.textlength(txt, font=f_a)
        d.text(((width - aw) / 2, ty), txt, font=f_a, fill=(200, 16, 46))

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
