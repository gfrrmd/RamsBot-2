"""
Mode verifikasi bukti bayar (diatur admin di Panel Admin → Pembayaran → Pengaturan):

  manual : semua bukti diputuskan admin (default).
  ocr    : OCR offline (RapidOCR) membaca nominal/waktu → cocok = VIP aktif otomatis.
  ai     : OCR + AI Gemini. AI memastikan gambar benar-benar bukti transfer, lalu hasilnya dicocokkan
           di kode. AI gagal → OCR; AI dan OCR gagal → manual.

Disimpan di bot_settings key `pay_auto_mode`. Key lama `pay_auto` ("1") otomatis dianggap mode `ocr`.
"""
from __future__ import annotations

from database import get_setting, set_setting
from utils.gemini import gemini_configured
from utils.receipt import ocr_available

MODES = ("manual", "ocr", "ai")
LABEL = {"manual": "Manual", "ocr": "OCR saja", "ai": "OCR + AI"}


def configured_mode() -> str:
    """Mode yang dipilih admin (belum memperhitungkan ketersediaan OCR / API key)."""
    m = get_setting("pay_auto_mode", "")
    if m in MODES:
        return m
    return "ocr" if get_setting("pay_auto", "0") == "1" else "manual"


def mode_problem(mode: str) -> str:
    """Alasan mode tidak bisa dipakai, atau string kosong bila siap."""
    if mode == "ocr" and not ocr_available():
        return "OCR tidak tersedia"
    if mode == "ai" and not gemini_configured():
        return "GEMINI_API_KEY belum diatur di Railway Variables"
    if mode == "ai" and not ocr_available():
        return ""            # tetap jalan, AI saja (tanpa pembanding OCR)
    return ""


def effective_mode() -> str:
    """Mode yang benar-benar dijalankan saat ini (turun ke OCR / manual bila prasyarat tidak ada)."""
    m = configured_mode()
    if m == "ai" and not gemini_configured():
        m = "ocr"
    if m == "ocr" and not ocr_available():
        m = "manual"
    return m


def next_mode(current: str) -> str:
    """Urutan tombol: manual → ocr → ai → manual. Mode yang prasyaratnya belum ada dilewati."""
    i = MODES.index(current) if current in MODES else 0
    for step in range(1, len(MODES) + 1):
        cand = MODES[(i + step) % len(MODES)]
        if cand == "manual" or not mode_problem(cand):
            return cand
    return "manual"


def set_mode(mode: str) -> None:
    set_setting("pay_auto_mode", mode)
    set_setting("pay_auto", "1" if mode != "manual" else "0")     # sinkron dengan key lama
