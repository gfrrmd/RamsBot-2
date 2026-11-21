import sys, os, asyncio, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from datetime import datetime, timedelta
from utils import gemini as G
from utils.gemini import AIReceipt, parse_ai_json, GeminiError, _to_amount
from utils.receipt import evaluate, combine

created = datetime(2026, 10, 19, 3, 0, 0)          # 10:00 WIB
deadline = created + timedelta(minutes=60)
T = 25012

def ai(**kw):
    base = dict(is_receipt=True, status="success", amount=T, date="2026-10-19", time="10:25", tz="WIB")
    base.update(kw)
    return AIReceipt(**base)

def ocr(rows): return evaluate(rows, T, created, deadline)
def run(a, o): return combine(a, o, T, created, deadline)

# ── parser ──
assert _to_amount(25012) == 25012 and _to_amount(25012.0) == 25012
assert _to_amount("25.012") == 25012 and _to_amount("Rp 1.250.000,00") == 1250000
assert _to_amount("25012.00") == 25012 and _to_amount("abc") is None and _to_amount(None) is None
r = parse_ai_json('```json\n{"is_transfer_receipt": true, "transfer_status": "SUCCESS", "amount_idr": "25.012", '
                  '"date": "2026-10-19", "time": "10.25", "timezone": "wib", "app_or_bank": "BCA", '
                  '"recipient_name": "TOKO", "looks_edited": false, "suspicious_signs": []}\n```')
assert r.is_receipt and r.status == "success" and r.amount == 25012 and r.time == "10:25" and r.tz == "WIB"
r = parse_ai_json('Hasil: {"is_transfer_receipt": "true", "amount_idr": null, "date": "kemarin"}')
assert r.is_receipt is False and r.amount is None and r.date is None      # "true" string ≠ true (ketat)
for bad in ("", "tidak ada json", "{rusak"):
    try: parse_ai_json(bad); raise SystemExit("harus gagal: " + bad)
    except GeminiError: pass

# ── combine ──
good_rows = ["Transfer Berhasil", "19 Okt 2026, 10:25:41 WIB", "Nominal Rp 25.012"]
r = run(ai(), ocr(good_rows)); print(1, r.status, r.source, r.note); assert r.status == "match" and r.source == "ai+ocr"
r = run(ai(), None); print(2, r.status, r.source); assert r.status == "match" and r.source == "ai"
r = run(ai(is_receipt=False), ocr(good_rows)); assert r.status == "not_receipt"
r = run(ai(status="failed"), ocr(good_rows)); assert r.status == "suspicious"
r = run(ai(edited=True, signs=["font beda"]), ocr(good_rows)); print(5, r.note); assert r.status == "suspicious"
r = run(ai(amount=25000), ocr(["Rp 25.000"])); assert r.status == "amount_mismatch"
r = run(ai(amount=25000), ocr(good_rows)); print(7, r.note); assert r.status == "suspicious"       # AI vs OCR bertentangan
r = run(ai(), ocr(["Rp 25.000"])); print(8, r.note); assert r.status == "suspicious"               # OCR membantah AI
r = run(ai(amount=None), ocr(good_rows)); print(9, r.status); assert r.status == "match"           # OCR melengkapi
r = run(ai(amount=None), ocr([])); assert r.status == "unreadable"
r = run(ai(time="11:30"), ocr(["Rp 25.012"])); print(11, r.status); assert r.status == "time_mismatch"
r = run(ai(date="2026-10-18"), None); assert r.status == "time_mismatch"                            # bukti kemarin
r = run(ai(date=None, time=None), ocr(good_rows)); assert r.status == "match" and r.time_checked == "datetime"  # waktu cadangan dari OCR
r = run(ai(date=None, time=None), ocr(["Rp 25.012"])); assert r.status == "match" and r.time_checked == "none"
r = run(ai(time="11:25", tz="WITA"), None); assert r.status == "match"                              # 11:25 WITA = 10:25 WIB
# AI gagal → OCR; keduanya gagal → error
r = run(None, ocr(good_rows)); print(16, r.status, r.source, r.note); assert r.status == "match" and r.source == "ocr"
r = run(None, ocr(["Rp 25.000"])); assert r.status == "amount_mismatch"
r = run(None, None); assert r.status == "error"

# ── analyze_receipt dengan HTTP di-mock ──
os.environ["GEMINI_API_KEY"] = "test"
os.environ["GEMINI_MODELS"] = "m-a,m-b"
G._calls.clear()
good = {"candidates": [{"content": {"parts": [{"text": json.dumps({
    "is_transfer_receipt": True, "transfer_status": "success", "amount_idr": 25012,
    "date": "2026-10-19", "time": "10:25", "timezone": "WIB", "looks_edited": False})}]}}]}
calls = []
def fake_post(model, body):
    calls.append(model)
    if model == "m-a": raise G._Retry("m-a: HTTP 429")
    # pastikan nominal order TIDAK ikut dikirim ke model
    assert "25012" not in json.dumps(body["contents"][0]["parts"][0])
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    return good
G._post = fake_post
res = asyncio.run(G.analyze_receipt(b"\xff\xd8\xff-bukan-gambar-asli"))
print(18, calls, res.model, res.amount); assert calls == ["m-a", "m-b"] and res.model == "m-b" and res.amount == 25012

def always_429(model, body): raise G._Retry(f"{model}: HTTP 429")
G._post = always_429
try: asyncio.run(G.analyze_receipt(b"x")); raise SystemExit("harus gagal")
except GeminiError as e: print(19, e)

G._post = lambda m, b: {"promptFeedback": {"blockReason": "SAFETY"}}
G._calls.clear()
try: asyncio.run(G.analyze_receipt(b"x")); raise SystemExit("harus gagal")
except GeminiError as e: print(20, e)

os.environ["GEMINI_RPM"] = "2"; G._calls.clear(); G._post = fake_post; calls.clear()
asyncio.run(G.analyze_receipt(b"x"))            # m-a gagal + m-b sukses = 2 permintaan lokal
try: asyncio.run(G.analyze_receipt(b"x")); raise SystemExit("pembatas lokal harus aktif")
except GeminiError as e: print(21, e); assert "pembatas lokal" in str(e)
del os.environ["GEMINI_API_KEY"]
try: asyncio.run(G.analyze_receipt(b"x")); raise SystemExit("tanpa key harus gagal")
except GeminiError as e: print(22, e)
print("ALL OK")
