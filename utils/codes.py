"""Helper murni (tanpa database) untuk token VIP, kode promo, voucher, dan pembatas percobaan."""
import math
import re
import secrets
import time
from datetime import datetime

# Tanpa huruf I, O dan angka 0, 1 supaya kode tidak ambigu saat disalin manual.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TOKEN_PREFIX = "RMS"
TOKEN_RANDOM_LEN = 12
MAX_TOKEN_USES = 3


class CodeError(Exception):
    """Kesalahan kode (token/promo/voucher). Pesan aman ditampilkan ke user.
    not_found=True berarti kode tidak dikenal, dihitung sebagai tebakan salah."""

    def __init__(self, message: str, not_found: bool = False):
        super().__init__(message)
        self.not_found = not_found


# ── Token VIP ─────────────────────────────────────────────────────────────────

def generate_token() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(TOKEN_RANDOM_LEN))
    return f"{TOKEN_PREFIX}-{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def normalize_token(text) -> str | None:
    """Rapikan input user (huruf kecil, tanpa strip, spasi) menjadi RMS-XXXX-XXXX-XXXX, atau None."""
    s = re.sub(r"[^A-Za-z0-9]", "", text or "").upper()
    if len(s) == TOKEN_RANDOM_LEN + len(TOKEN_PREFIX) and s.startswith(TOKEN_PREFIX):
        s = s[len(TOKEN_PREFIX):]
    if len(s) != TOKEN_RANDOM_LEN or any(ch not in CODE_ALPHABET for ch in s):
        return None
    return f"{TOKEN_PREFIX}-{s[:4]}-{s[4:8]}-{s[8:]}"


# ── Kode promo & voucher ──────────────────────────────────────────────────────

def generate_code(length: int = 8) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def normalize_code(text) -> str | None:
    """Kode promo/voucher: huruf besar, angka, _ atau -, panjang 3 sampai 20."""
    s = (text or "").strip().upper()
    return s if re.fullmatch(r"[A-Z0-9_-]{3,20}", s) else None


def parse_percent(text) -> int | None:
    m = re.fullmatch(r"\s*(\d{1,3})\s*%?\s*", text or "")
    if not m:
        return None
    v = int(m.group(1))
    return v if 1 <= v <= 100 else None


def calc_discount(price: int, percent: int) -> tuple[int, int]:
    """Return (diskon, harga akhir). Diskon dibulatkan ke bawah, harga akhir tidak pernah negatif."""
    discount = max(0, min(price, price * percent // 100))
    return discount, price - discount


def promo_problem(p: dict | None, used: int, user_used: int, now: datetime) -> CodeError | None:
    """Cek apakah promo boleh dipakai. Return CodeError bila tidak, None bila lolos."""
    if not p or not p.get("is_active"):
        return CodeError("Kode promo tidak ditemukan atau sudah tidak aktif.", not_found=True)
    if p.get("expires_at") and datetime.fromisoformat(p["expires_at"]) <= now:
        return CodeError("Kode promo sudah kedaluwarsa.")
    if p.get("max_uses") and used >= p["max_uses"]:
        return CodeError("Kuota kode promo sudah habis.")
    if user_used > 0:
        return CodeError("Kamu sudah pernah memakai kode promo ini.")
    return None


# ── Pembatas percobaan (anti tebak-tebak kode) ────────────────────────────────

class AttemptLimiter:
    """Setelah max_fails tebakan salah dalam window detik, user dikunci selama lock detik."""

    def __init__(self, max_fails: int = 6, window: int = 600, lock: int = 900, clock=time.monotonic):
        self.max_fails, self.window, self.lock, self._clock = max_fails, window, lock, clock
        self._fails: dict[int, list[float]] = {}
        self._until: dict[int, float] = {}

    def blocked_for(self, uid: int) -> int:
        """Sisa detik terkunci (0 jika tidak terkunci)."""
        until = self._until.get(uid)
        if until is None:
            return 0
        left = until - self._clock()
        if left > 0:
            return math.ceil(left)
        self._until.pop(uid, None)
        return 0

    def fail(self, uid: int) -> None:
        now = self._clock()
        recent = [t for t in self._fails.get(uid, []) if now - t < self.window]
        recent.append(now)
        if len(recent) >= self.max_fails:
            self._until[uid] = now + self.lock
            recent = []
        self._fails[uid] = recent

    def reset(self, uid: int) -> None:
        self._fails.pop(uid, None)
        self._until.pop(uid, None)


limiter = AttemptLimiter()


def blocked_message(seconds: int) -> str:
    return f"⏳ Terlalu banyak percobaan salah. Coba lagi dalam {max(1, math.ceil(seconds / 60))} menit."
