import sys; sys.path.insert(0, __import__('os').path.join(__import__('os').path.dirname(__file__), '..'))
from datetime import datetime, timedelta
from utils.codes import (AttemptLimiter, CODE_ALPHABET, calc_discount, generate_code, generate_token,
                         normalize_code, normalize_token, parse_percent, promo_problem)

# ── token: format, keunikan, normalisasi
for _ in range(200):
    t = generate_token()
    assert len(t) == 18 and t.startswith("RMS-") and t.count("-") == 3, t
    assert all(ch in CODE_ALPHABET for ch in t.replace("-", "")[3:]), t
    assert normalize_token(t) == t
assert len({generate_token() for _ in range(500)}) == 500
assert normalize_token("rms-abcd-efgh-jklm") == "RMS-ABCD-EFGH-JKLM"
assert normalize_token("  RMSABCDEFGHJKLM ") == "RMS-ABCD-EFGH-JKLM"
assert normalize_token("abcd efgh jklm") == "RMS-ABCD-EFGH-JKLM"        # tanpa prefix
assert normalize_token("RMS-RMSA-BCDE-FGHJ") == "RMS-RMSA-BCDE-FGHJ"    # bagian acak kebetulan diawali RMS
assert normalize_token("RMSABCDEFGHJ") == "RMS-RMSA-BCDE-FGHJ"          # 12 karakter tanpa prefix, diawali RMS
assert normalize_token("RMS-ABCD-EFGH") is None
assert normalize_token("RMS-ABCD-EFGH-JKL0") is None                    # 0 tidak ada di alfabet
assert normalize_token("") is None and normalize_token(None) is None

# ── kode promo / voucher
assert normalize_code("hemat20") == "HEMAT20"
assert normalize_code(" gratis-7_a ") == "GRATIS-7_A"
assert normalize_code("ab") is None and normalize_code("a" * 21) is None and normalize_code("ha mat") is None
assert normalize_code("kode!") is None
assert len(generate_code(10)) == 10

# ── persen & diskon
assert parse_percent("20") == 20 and parse_percent("20%") == 20 and parse_percent(" 100 ") == 100
assert parse_percent("0") is None and parse_percent("101") is None and parse_percent("abc") is None
assert parse_percent("-5") is None and parse_percent("") is None
assert calc_discount(25000, 20) == (5000, 20000)
assert calc_discount(25000, 100) == (25000, 0)
assert calc_discount(25000, 1) == (250, 24750)
assert calc_discount(9999, 33) == (3299, 6700)          # diskon dibulatkan ke bawah
assert calc_discount(0, 50) == (0, 0)

# ── validasi promo
now = datetime(2026, 10, 20, 12, 0, 0)
ok = {"is_active": True, "expires_at": None, "max_uses": 0}
assert promo_problem(ok, 999, 0, now) is None                                    # kuota 0 = tanpa batas
assert promo_problem(None, 0, 0, now).not_found
assert promo_problem({**ok, "is_active": False}, 0, 0, now).not_found
assert promo_problem({**ok, "expires_at": (now - timedelta(seconds=1)).isoformat()}, 0, 0, now) is not None
assert promo_problem({**ok, "expires_at": (now + timedelta(days=1)).isoformat()}, 0, 0, now) is None
assert "Kuota" in str(promo_problem({**ok, "max_uses": 5}, 5, 0, now))
assert promo_problem({**ok, "max_uses": 5}, 4, 0, now) is None
assert "sudah pernah" in str(promo_problem(ok, 1, 1, now))

# ── pembatas percobaan
clock = [0.0]
lim = AttemptLimiter(max_fails=3, window=60, lock=120, clock=lambda: clock[0])
assert lim.blocked_for(1) == 0
lim.fail(1); lim.fail(1)
assert lim.blocked_for(1) == 0
lim.fail(1)
assert lim.blocked_for(1) == 120
assert lim.blocked_for(2) == 0                                                   # user lain tidak terpengaruh
clock[0] = 119; assert lim.blocked_for(1) == 1
clock[0] = 121; assert lim.blocked_for(1) == 0
lim.fail(1); clock[0] += 61; lim.fail(1); lim.fail(1)                            # kegagalan lama kedaluwarsa
assert lim.blocked_for(1) == 0
lim.fail(1); assert lim.blocked_for(1) > 0
lim.reset(1); assert lim.blocked_for(1) == 0
print("test_codes OK")
