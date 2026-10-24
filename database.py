from datetime import datetime, timedelta, timezone

import psycopg2

from config import DATABASE_URL
from utils.codes import MAX_TOKEN_USES, CodeError, generate_code, generate_token, promo_problem


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TEXT
        )
    """)
    c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_used INTEGER DEFAULT 0")
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            user_id BIGINT PRIMARY KEY,
            api_id BIGINT NOT NULL,
            api_hash TEXT NOT NULL,
            string_session TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id BIGINT PRIMARY KEY,
            plan TEXT DEFAULT 'vip',
            paid_at TEXT,
            expired_at TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id BIGINT PRIMARY KEY,
            auto_dl_view_once INTEGER DEFAULT 0
        )
    """)
    c.execute("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS auto_dl_view_once INTEGER DEFAULT 0")
    c.execute("""
        CREATE TABLE IF NOT EXISTS blacklist_channels (
            id SERIAL PRIMARY KEY,
            identifier TEXT NOT NULL UNIQUE,
            note TEXT,
            added_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS bc_group_blacklist (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            group_id BIGINT NOT NULL,
            group_name TEXT,
            added_at TEXT NOT NULL,
            UNIQUE (user_id, group_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS auto_block_channels (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            channel_name TEXT,
            UNIQUE(user_id, channel_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS rich_targets (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            chat_id BIGINT NOT NULL,
            title TEXT,
            chat_type TEXT,
            added_at TEXT NOT NULL,
            UNIQUE (user_id, chat_id)
        )
    """)
    # ── Tabel baru (v2) ──
    c.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS reminder_stage INTEGER DEFAULT 0")
    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_qris (
            user_id BIGINT PRIMARY KEY,
            qris_string TEXT NOT NULL,
            merchant_name TEXT,
            merchant_city TEXT,
            updated_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            days INTEGER NOT NULL,
            price BIGINT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            plan_id INTEGER,
            plan_name TEXT,
            days INTEGER NOT NULL,
            base_price BIGINT NOT NULL,
            unique_code INTEGER DEFAULT 0,
            total BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            qris_payload TEXT,
            proof_file_id TEXT,
            created_at TEXT,
            updated_at TEXT,
            paid_at TEXT,
            handled_by BIGINT
        )
    """)
    # v3: verifikasi otomatis bukti bayar (OCR) & pembatalan oleh admin
    c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS proof_hash TEXT")
    c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS verified_by TEXT")
    c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS verify_note TEXT")
    c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS ocr_attempts INTEGER DEFAULT 0")
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_proof_hash ON orders(proof_hash)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    # v4: token VIP, kode promo, voucher
    c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS promo_id INTEGER")
    c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS promo_code TEXT")
    c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount BIGINT DEFAULT 0")
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_promo ON orders(promo_id)")
    c.execute("""
        CREATE TABLE IF NOT EXISTS vip_tokens (
            token TEXT PRIMARY KEY,
            holder_id BIGINT NOT NULL UNIQUE,
            uses INTEGER NOT NULL DEFAULT 0,
            max_uses INTEGER NOT NULL DEFAULT 3,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vip_token_log (
            id SERIAL PRIMARY KEY,
            token TEXT NOT NULL,
            from_id BIGINT NOT NULL,
            to_id BIGINT NOT NULL,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            id SERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            percent INTEGER NOT NULL,
            max_uses INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vouchers (
            id SERIAL PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            days INTEGER NOT NULL,
            max_claims INTEGER NOT NULL DEFAULT 1,
            expires_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS voucher_claims (
            id SERIAL PRIMARY KEY,
            voucher_id INTEGER NOT NULL,
            user_id BIGINT NOT NULL,
            claimed_at TEXT,
            UNIQUE (voucher_id, user_id)
        )
    """)
    conn.commit()
    conn.close()


def upsert_user(user_id, username, full_name):
    conn = get_conn(); c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, username, full_name, created_at)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT(user_id) DO UPDATE SET username=EXCLUDED.username, full_name=EXCLUDED.full_name
    """, (user_id, username, full_name, datetime.now().isoformat()))
    conn.commit(); conn.close()


def get_user_display_name(user_id: int) -> str:
    """Ambil nama depan user dari DB. Fallback ke ID jika tidak ada."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT full_name FROM users WHERE user_id=%s", (user_id,))
    row = c.fetchone(); conn.close()
    if row and row[0]:
        first_name = row[0].strip().split()[0]
        return first_name
    return str(user_id)


def get_vip_username(user_id: int) -> str | None:
    """Ambil username user VIP dari DB. Return None jika tidak ada."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT username FROM users WHERE user_id=%s", (user_id,))
    row = c.fetchone(); conn.close()
    if row and row[0]:
        return row[0].lstrip("@")
    return None


def save_user_session(user_id, api_id, api_hash, string_session):
    conn = get_conn(); c = conn.cursor()
    c.execute("""
        INSERT INTO sessions (user_id, api_id, api_hash, string_session)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT(user_id) DO UPDATE SET api_id=EXCLUDED.api_id, api_hash=EXCLUDED.api_hash, string_session=EXCLUDED.string_session
    """, (user_id, api_id, api_hash, string_session))
    conn.commit(); conn.close()


def get_user_session(user_id):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT api_id, api_hash, string_session FROM sessions WHERE user_id=%s", (user_id,))
    row = c.fetchone(); conn.close()
    return {"api_id": row[0], "api_hash": row[1], "string_session": row[2]} if row else None


def delete_user_session(user_id):
    conn = get_conn(); c = conn.cursor(); c.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
    conn.commit(); conn.close()


def is_subscribed(user_id):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT expired_at FROM subscriptions WHERE user_id=%s AND is_active=1", (user_id,))
    row = c.fetchone(); conn.close()
    if not row:
        return False
    return datetime.now() < datetime.fromisoformat(row[0])


def get_subscription_info(user_id):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT paid_at, expired_at, is_active, plan FROM subscriptions WHERE user_id=%s", (user_id,))
    row = c.fetchone(); conn.close(); return row


def activate_subscription(user_id, days=30):
    now = datetime.now(); expired = now + timedelta(days=days)
    conn = get_conn(); c = conn.cursor()
    c.execute("""
        INSERT INTO subscriptions (user_id, plan, paid_at, expired_at, is_active, reminder_stage)
        VALUES (%s,'vip',%s,%s,1,0)
        ON CONFLICT(user_id) DO UPDATE SET paid_at=EXCLUDED.paid_at, expired_at=EXCLUDED.expired_at, is_active=1, plan='vip', reminder_stage=0
    """, (user_id, now.isoformat(), expired.isoformat()))
    conn.commit(); conn.close(); return expired


# Ubah nilai minutes di sini untuk mengatur durasi trial
TRIAL_DURATION_MINUTES = 5


def activate_trial(user_id):
    minutes = TRIAL_DURATION_MINUTES
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT trial_used FROM users WHERE user_id=%s", (user_id,))
    row = c.fetchone()
    if row and row[0]:
        conn.close()
        return False, None, minutes
    c.execute("UPDATE users SET trial_used=1 WHERE user_id=%s", (user_id,))
    now = datetime.now()
    expired = now + timedelta(minutes=minutes)
    c.execute("""
        INSERT INTO subscriptions (user_id, plan, paid_at, expired_at, is_active)
        VALUES (%s,'trial',%s,%s,1)
        ON CONFLICT(user_id) DO UPDATE SET paid_at=EXCLUDED.paid_at, expired_at=EXCLUDED.expired_at, is_active=1, plan='trial'
    """, (user_id, now.isoformat(), expired.isoformat()))
    conn.commit(); conn.close()
    return True, expired, minutes


def has_used_trial(user_id) -> bool:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT trial_used FROM users WHERE user_id=%s", (user_id,))
    row = c.fetchone(); conn.close()
    return bool(row and row[0])


def revoke_subscription(user_id):
    conn = get_conn(); c = conn.cursor(); c.execute("UPDATE subscriptions SET is_active=0 WHERE user_id=%s", (user_id,))
    conn.commit(); conn.close()


def get_user_by_username(username):
    conn = get_conn(); c = conn.cursor(); username_clean = username.lstrip("@").lower()
    c.execute("SELECT user_id FROM users WHERE LOWER(username)=%s", (username_clean,))
    row = c.fetchone(); conn.close(); return row[0] if row else None


def get_auto_dl_view_once(user_id):
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT auto_dl_view_once FROM user_settings WHERE user_id=%s", (user_id,))
    row = c.fetchone(); conn.close(); return bool(row[0]) if row else False


def set_auto_dl_view_once(user_id, enabled: bool):
    conn = get_conn(); c = conn.cursor()
    c.execute("""
        INSERT INTO user_settings (user_id, auto_dl_view_once)
        VALUES (%s, %s)
        ON CONFLICT(user_id) DO UPDATE SET auto_dl_view_once=EXCLUDED.auto_dl_view_once
    """, (user_id, 1 if enabled else 0))
    conn.commit(); conn.close()


def blacklist_add(identifier: str, note: str = "") -> bool:
    clean = identifier.strip().lstrip("@"); conn = get_conn(); c = conn.cursor()
    try:
        c.execute("INSERT INTO blacklist_channels (identifier, note, added_at) VALUES (%s,%s,%s)", (clean, note or "", datetime.now().isoformat()))
        conn.commit(); return True
    except psycopg2.errors.UniqueViolation:
        conn.rollback(); return False
    finally:
        conn.close()


def blacklist_remove(identifier: str) -> bool:
    clean = identifier.strip().lstrip("@"); conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM blacklist_channels WHERE identifier=%s", (clean,)); deleted = c.rowcount
    conn.commit(); conn.close(); return deleted > 0


def blacklist_list() -> list[dict]:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT identifier, note, added_at FROM blacklist_channels ORDER BY added_at DESC")
    rows = c.fetchall(); conn.close()
    return [{"identifier": r[0], "note": r[1], "added_at": r[2]} for r in rows]


def is_channel_blacklisted(identifier: str) -> bool:
    from utils.helpers import _normalize_channel_id
    variants = _normalize_channel_id(identifier)
    conn = get_conn(); c = conn.cursor(); c.execute("SELECT identifier FROM blacklist_channels")
    rows = c.fetchall(); conn.close()
    return any(variants & _normalize_channel_id(db_id) for (db_id,) in rows)


def bc_blacklist_add(user_id: int, group_id: int, group_name: str = "") -> bool:
    conn = get_conn(); c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO bc_group_blacklist (user_id, group_id, group_name, added_at)
            VALUES (%s,%s,%s,%s) ON CONFLICT (user_id, group_id) DO NOTHING
        """, (user_id, group_id, group_name or "", datetime.now().isoformat()))
        conn.commit(); return c.rowcount > 0
    finally:
        conn.close()


def bc_blacklist_remove(user_id: int, group_id: int) -> bool:
    conn = get_conn(); c = conn.cursor(); c.execute("DELETE FROM bc_group_blacklist WHERE user_id=%s AND group_id=%s", (user_id, group_id))
    deleted = c.rowcount; conn.commit(); conn.close(); return deleted > 0


def bc_blacklist_get(user_id: int) -> list[dict]:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT group_id, group_name, added_at FROM bc_group_blacklist WHERE user_id=%s ORDER BY added_at DESC", (user_id,))
    rows = c.fetchall(); conn.close()
    return [{"group_id": r[0], "group_name": r[1], "added_at": r[2]} for r in rows]


def bc_blacklist_ids(user_id: int) -> set:
    conn = get_conn(); c = conn.cursor(); c.execute("SELECT group_id FROM bc_group_blacklist WHERE user_id=%s", (user_id,))
    rows = c.fetchall(); conn.close(); return {r[0] for r in rows}


# ── Auto Block Leaver ──────────────────────────────────────────────────────────

def add_auto_block_channel(user_id: int, channel_id: int, channel_name: str = "") -> bool:
    conn = get_conn(); c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO auto_block_channels (user_id, channel_id, channel_name)
            VALUES (%s, %s, %s) ON CONFLICT(user_id, channel_id) DO NOTHING
        """, (user_id, channel_id, channel_name or ""))
        conn.commit(); return c.rowcount > 0
    finally:
        conn.close()


def remove_auto_block_channel(user_id: int, channel_id: int) -> bool:
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM auto_block_channels WHERE user_id=%s AND channel_id=%s", (user_id, channel_id))
    deleted = c.rowcount; conn.commit(); conn.close(); return deleted > 0


def get_auto_block_channels(user_id: int) -> list[dict]:
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT channel_id, channel_name FROM auto_block_channels WHERE user_id=%s", (user_id,))
    rows = c.fetchall(); conn.close()
    return [{"channel_id": r[0], "channel_name": r[1]} for r in rows]


def get_all_auto_block_channel_owners(channel_id: int) -> list[int]:
    """Kembalikan semua user_id yang memantau channel_id ini."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT user_id FROM auto_block_channels WHERE channel_id=%s", (channel_id,))
    rows = c.fetchall(); conn.close()
    return [r[0] for r in rows]


# ── VIP List ───────────────────────────────────────────────────────────────────

def get_all_vip_users() -> list[dict]:
    """Ambil semua user VIP aktif beserta info lengkap dari DB."""
    conn = get_conn(); c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.username, u.full_name, s.paid_at, s.expired_at
        FROM subscriptions s
        JOIN users u ON s.user_id = u.user_id
        WHERE s.is_active = 1 AND s.plan = 'vip'
        ORDER BY s.expired_at ASC
    """)
    rows = c.fetchall(); conn.close()
    return [
        {
            "user_id": r[0],
            "username": r[1],
            "full_name": r[2],
            "paid_at": r[3],
            "expired_at": r[4],
        }
        for r in rows
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  v2 — helper, pengaturan, QRIS user, paket, order, statistik
# ══════════════════════════════════════════════════════════════════════════════

_WIB = timezone(timedelta(hours=7))


def _run(sql, params=(), fetch=None):
    """Eksekusi 1 query. fetch: None | 'one' | 'all' | 'rowcount'. Selalu commit & close."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(sql, params)
        res = None
        if fetch == "one":
            res = c.fetchone()
        elif fetch == "all":
            res = c.fetchall()
        elif fetch == "rowcount":
            res = c.rowcount
        conn.commit()
        return res
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now().isoformat()


# ── Pengaturan bot (key-value) ─────────────────────────────────────────────────

def get_setting(key: str, default=None):
    row = _run("SELECT value FROM bot_settings WHERE key=%s", (key,), "one")
    return row[0] if row and row[0] is not None else default


def set_setting(key: str, value) -> None:
    _run(
        "INSERT INTO bot_settings (key, value) VALUES (%s,%s) "
        "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
        (key, str(value)),
    )


def delete_setting(key: str) -> None:
    _run("DELETE FROM bot_settings WHERE key=%s", (key,))


# ── QRIS statis milik user VIP ─────────────────────────────────────────────────

def save_user_qris(user_id: int, qris_string: str, merchant_name: str = "", merchant_city: str = "") -> None:
    _run(
        """
        INSERT INTO user_qris (user_id, qris_string, merchant_name, merchant_city, updated_at)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT(user_id) DO UPDATE SET qris_string=EXCLUDED.qris_string,
            merchant_name=EXCLUDED.merchant_name, merchant_city=EXCLUDED.merchant_city,
            updated_at=EXCLUDED.updated_at
        """,
        (user_id, qris_string, merchant_name, merchant_city, _now_iso()),
    )


def get_user_qris(user_id: int) -> dict | None:
    row = _run(
        "SELECT qris_string, merchant_name, merchant_city, updated_at FROM user_qris WHERE user_id=%s",
        (user_id,), "one",
    )
    if not row:
        return None
    return {"qris_string": row[0], "merchant_name": row[1] or "", "merchant_city": row[2] or "", "updated_at": row[3]}


def delete_user_qris(user_id: int) -> bool:
    return (_run("DELETE FROM user_qris WHERE user_id=%s", (user_id,), "rowcount") or 0) > 0


# ── Langganan: perpanjang (menumpuk) ───────────────────────────────────────────

def _extend_sub_cur(c, user_id: int, days: int) -> datetime:
    """Isi logika perpanjang pada cursor yang sudah ada (dipakai juga di dalam transaksi lain)."""
    now = datetime.now()
    c.execute("SELECT paid_at, expired_at, is_active, plan FROM subscriptions WHERE user_id=%s", (user_id,))
    row = c.fetchone()
    base, paid_at = now, now.isoformat()
    if row and row[2] and row[3] == "vip":
        try:
            cur_exp = datetime.fromisoformat(row[1])
            if cur_exp > now:
                base = cur_exp
                paid_at = row[0] or paid_at       # pertahankan tanggal mulai VIP
        except Exception:
            pass
    expired = base + timedelta(days=days)
    c.execute(
        """
        INSERT INTO subscriptions (user_id, plan, paid_at, expired_at, is_active, reminder_stage)
        VALUES (%s,'vip',%s,%s,1,0)
        ON CONFLICT(user_id) DO UPDATE SET paid_at=EXCLUDED.paid_at, expired_at=EXCLUDED.expired_at,
            is_active=1, plan='vip', reminder_stage=0
        """,
        (user_id, paid_at, expired.isoformat()),
    )
    return expired


def extend_subscription(user_id: int, days: int) -> datetime:
    """
    Tambah masa VIP. Jika VIP masih aktif, hari ditambahkan di atas tanggal expired
    saat ini (perpanjang). Jika belum/sudah habis/trial, hitung dari sekarang.
    """
    conn = get_conn()
    try:
        expired = _extend_sub_cur(conn.cursor(), user_id, days)
        conn.commit()
        return expired
    finally:
        conn.close()


# ── Paket VIP ──────────────────────────────────────────────────────────────────

def _plan(r) -> dict:
    return {"id": r[0], "name": r[1], "days": r[2], "price": r[3], "is_active": bool(r[4])}


def add_plan(name: str, days: int, price: int) -> int:
    row = _run(
        "INSERT INTO plans (name, days, price, is_active, created_at) VALUES (%s,%s,%s,1,%s) RETURNING id",
        (name, days, price, _now_iso()), "one",
    )
    return row[0]


def update_plan(plan_id: int, name: str, days: int, price: int) -> bool:
    return (_run("UPDATE plans SET name=%s, days=%s, price=%s WHERE id=%s", (name, days, price, plan_id), "rowcount") or 0) > 0


def set_plan_active(plan_id: int, active: bool) -> None:
    _run("UPDATE plans SET is_active=%s WHERE id=%s", (1 if active else 0, plan_id))


def delete_plan(plan_id: int) -> bool:
    return (_run("DELETE FROM plans WHERE id=%s", (plan_id,), "rowcount") or 0) > 0


def get_plans(active_only: bool = False) -> list[dict]:
    sql = "SELECT id, name, days, price, is_active FROM plans"
    if active_only:
        sql += " WHERE is_active=1"
    sql += " ORDER BY days ASC, id ASC"
    return [_plan(r) for r in _run(sql, (), "all")]


def get_plan(plan_id: int) -> dict | None:
    r = _run("SELECT id, name, days, price, is_active FROM plans WHERE id=%s", (plan_id,), "one")
    return _plan(r) if r else None


# ── Order pembayaran ───────────────────────────────────────────────────────────

_ORDER_COLS = ("id, user_id, plan_id, plan_name, days, base_price, unique_code, total, status, "
               "qris_payload, proof_file_id, created_at, updated_at, paid_at, handled_by, verified_by, verify_note, "
               "promo_id, promo_code, discount")
_ORDER_KEYS = [k.strip() for k in _ORDER_COLS.split(",")]


def _order(r) -> dict:
    return dict(zip(_ORDER_KEYS, r))


def active_order_totals() -> set[int]:
    rows = _run("SELECT total FROM orders WHERE status IN ('pending','verifying')", (), "all")
    return {r[0] for r in rows}


def create_order(user_id: int, plan: dict, unique_code: int, total: int, qris_payload: str,
                 promo: dict | None = None, discount: int = 0) -> int:
    """
    Buat order. Jika promo diberikan, kuota & batas per-user dicek ulang di dalam transaksi
    yang mengunci baris promo (anti dua user merebut kuota terakhir). Raise CodeError bila ditolak.
    total = harga paket - diskon + kode unik (dihitung pemanggil).
    """
    now = _now_iso()
    cols = ("INSERT INTO orders (user_id, plan_id, plan_name, days, base_price, unique_code, total, status, "
            "qris_payload, created_at, updated_at, promo_id, promo_code, discount) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s,%s,%s) RETURNING id")
    params = (user_id, plan["id"], plan["name"], plan["days"], plan["price"], unique_code, total,
              qris_payload, now, now, promo["id"] if promo else None, promo["code"] if promo else None,
              discount if promo else 0)
    if not promo:
        return _run(cols, params, "one")[0]
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(f"SELECT {_PROMO_COLS} FROM promo_codes WHERE id=%s FOR UPDATE", (promo["id"],))
        r = c.fetchone()
        fresh = _promo(r) if r else None
        used, user_used = _promo_counts(c, promo["id"], user_id)
        problem = promo_problem(fresh, used, user_used, datetime.now())
        if problem:
            raise problem
        c.execute(cols, params)
        oid = c.fetchone()[0]
        conn.commit()
        return oid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_order(order_id: int) -> dict | None:
    r = _run(f"SELECT {_ORDER_COLS} FROM orders WHERE id=%s", (order_id,), "one")
    return _order(r) if r else None


def get_open_order(user_id: int) -> dict | None:
    """Order terbaru milik user yang masih menunggu pembayaran / verifikasi."""
    r = _run(
        f"SELECT {_ORDER_COLS} FROM orders WHERE user_id=%s AND status IN ('pending','verifying') "
        "ORDER BY id DESC LIMIT 1", (user_id,), "one",
    )
    return _order(r) if r else None


def set_order_proof(order_id: int, file_id: str, proof_hash: str | None = None, status: str = "verifying") -> bool:
    """Simpan bukti bayar. status='pending' dipakai saat OCR gagal & user diminta kirim ulang."""
    return (_run(
        "UPDATE orders SET proof_file_id=%s, proof_hash=%s, status=%s, updated_at=%s "
        "WHERE id=%s AND status IN ('pending','verifying')",
        (file_id, proof_hash, status, _now_iso(), order_id), "rowcount",
    ) or 0) > 0


def bump_ocr_attempts(order_id: int) -> int:
    row = _run("UPDATE orders SET ocr_attempts=COALESCE(ocr_attempts,0)+1 WHERE id=%s RETURNING ocr_attempts",
               (order_id,), "one")
    return row[0] if row else 0


def find_duplicate_proof(proof_hash: str, exclude_order_id: int) -> dict | None:
    """Order LAIN yang sudah memakai gambar bukti identik (anti bukti dipakai ulang)."""
    r = _run(
        f"SELECT {_ORDER_COLS} FROM orders WHERE proof_hash=%s AND id<>%s "
        "AND status IN ('verifying','paid','rejected','revoked') ORDER BY id DESC LIMIT 1",
        (proof_hash, exclude_order_id), "one",
    )
    return _order(r) if r else None


def set_order_note(order_id: int, note: str) -> None:
    _run("UPDATE orders SET verify_note=%s WHERE id=%s", (note[:500], order_id))


def update_order_status(order_id: int, status: str, only_from: tuple = (), handled_by: int | None = None) -> bool:
    sql = "UPDATE orders SET status=%s, updated_at=%s, handled_by=COALESCE(%s, handled_by) WHERE id=%s"
    params: list = [status, _now_iso(), handled_by, order_id]
    if only_from:
        sql += " AND status IN (" + ",".join(["%s"] * len(only_from)) + ")"
        params += list(only_from)
    return (_run(sql, tuple(params), "rowcount") or 0) > 0


def approve_order(order_id: int, admin_id: int, verified_by: str = "admin", note: str | None = None) -> dict | None:
    """
    Setujui order secara atomik (anti double-approve) lalu perpanjang VIP.
    verified_by: 'admin' (manual) atau 'auto' (OCR). admin_id=0 untuk persetujuan bot.
    Return order (dengan key 'new_expired') atau None jika sudah diproses.
    """
    now = _now_iso()
    changed = _run(
        "UPDATE orders SET status='paid', paid_at=%s, updated_at=%s, handled_by=%s, verified_by=%s, "
        "verify_note=COALESCE(%s, verify_note) "
        "WHERE id=%s AND status IN ('pending','verifying','expired')",
        (now, now, admin_id, verified_by, note, order_id), "rowcount",
    )
    if not changed:
        return None
    order = get_order(order_id)
    order["new_expired"] = extend_subscription(order["user_id"], order["days"])
    # Setiap pembelian VIP menerbitkan token baru: kode berganti dan pemakaian kembali ke 0.
    order["token"] = issue_token(order["user_id"])
    return order


def _sub_is_live(row, now: datetime) -> bool:
    """row = (expired_at, is_active, plan). True bila VIP berbayar masih aktif dan belum habis."""
    if not row or not row[1] or row[2] != "vip":
        return False
    try:
        return datetime.fromisoformat(row[0]) > now
    except Exception:
        return False


def _follow_token_chain(user_id: int, max_hops: int = 5) -> int:
    """Telusuri perpindahan token dari user_id sampai pemegang terakhir (maks 3x pindah, batas hop berjaga-jaga)."""
    current, seen = user_id, {user_id}
    for _ in range(max_hops):
        r = _run("SELECT to_id FROM vip_token_log WHERE from_id=%s ORDER BY id DESC LIMIT 1", (current,), "one")
        if not r or r[0] in seen:
            break
        current = r[0]
        seen.add(current)
    return current


def revoke_paid_order(order_id: int, admin_id: int) -> dict | None:
    """
    Batalkan order yang sudah 'paid' (mis. bukti dipalsukan): status → 'revoked' dan hari yang
    diberikan order ini DIKURANGI dari masa VIP (hari dari pembelian sah lain tetap utuh).
    Jika sisa masa VIP jadi <= 0, langganan dinonaktifkan. Return order + 'new_expired' + 'deactivated'.
    """
    changed = _run(
        "UPDATE orders SET status='revoked', updated_at=%s, handled_by=%s WHERE id=%s AND status='paid'",
        (_now_iso(), admin_id, order_id), "rowcount",
    )
    if not changed:
        return None
    order = get_order(order_id)
    uid, now = order["user_id"], datetime.now()
    row = _run("SELECT expired_at, is_active, plan FROM subscriptions WHERE user_id=%s", (uid,), "one")
    if not _sub_is_live(row, now):
        # VIP pembeli mungkin sudah dipindahkan lewat token (mis. bukti palsu lalu langsung pindah akun):
        # ikuti rantai perpindahan agar pembatalan mengenai pemegang VIP saat ini.
        holder = _follow_token_chain(uid)
        if holder != uid:
            uid = holder
            row = _run("SELECT expired_at, is_active, plan FROM subscriptions WHERE user_id=%s", (uid,), "one")
    order["holder_id"] = uid
    order["new_expired"], order["deactivated"] = None, False
    if row and row[1] and row[2] == "vip":
        try:
            new_exp = datetime.fromisoformat(row[0]) - timedelta(days=order["days"])
        except Exception:
            new_exp = now
        if new_exp <= now:
            _run("UPDATE subscriptions SET is_active=0, expired_at=%s WHERE user_id=%s", (now.isoformat(), uid))
            order["deactivated"] = True
        else:
            _run("UPDATE subscriptions SET expired_at=%s, reminder_stage=0 WHERE user_id=%s", (new_exp.isoformat(), uid))
        order["new_expired"] = new_exp
    return order


# ── Daftar user yang WAJIB verifikasi manual (mis. setelah terbukti curang) ────

def get_manual_only_users() -> set[int]:
    raw = get_setting("pay_manual_users", "") or ""
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


def add_manual_only_user(user_id: int) -> None:
    ids = get_manual_only_users() | {int(user_id)}
    set_setting("pay_manual_users", ",".join(str(i) for i in sorted(ids)))


def _order_where(status, verified_by) -> tuple[str, list]:
    conds, params = [], []
    if status:
        statuses = (status,) if isinstance(status, str) else tuple(status)
        conds.append("status IN (" + ",".join(["%s"] * len(statuses)) + ")")
        params += list(statuses)
    if verified_by:
        conds.append("verified_by=%s")
        params.append(verified_by)
    return (" WHERE " + " AND ".join(conds)) if conds else "", params


def list_orders(status: str | tuple | None = None, limit: int = 8, offset: int = 0,
                verified_by: str | None = None) -> list[dict]:
    where, params = _order_where(status, verified_by)
    sql = f"SELECT {_ORDER_COLS} FROM orders{where} ORDER BY id DESC LIMIT %s OFFSET %s"
    return [_order(r) for r in _run(sql, tuple(params + [limit, offset]), "all")]


def count_orders(status: str | tuple | None = None, verified_by: str | None = None) -> int:
    where, params = _order_where(status, verified_by)
    return _run(f"SELECT COUNT(*) FROM orders{where}", tuple(params), "one")[0]


def get_user_orders(user_id: int, limit: int = 8) -> list[dict]:
    rows = _run(f"SELECT {_ORDER_COLS} FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT %s", (user_id, limit), "all")
    return [_order(r) for r in rows]


def expire_stale_orders(minutes: int) -> list[dict]:
    """Tandai order 'pending' yang melewati batas waktu sebagai 'expired'."""
    cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
    rows = _run(
        f"SELECT {_ORDER_COLS} FROM orders WHERE status='pending' AND created_at < %s", (cutoff,), "all",
    )
    if rows:
        _run("UPDATE orders SET status='expired', updated_at=%s WHERE status='pending' AND created_at < %s",
             (_now_iso(), cutoff))
    return [_order(r) for r in rows]


# ── Statistik & manajemen user (admin) ─────────────────────────────────────────

def _scalar(sql, params=()):
    return _run(sql, params, "one")[0] or 0


def revenue_since(iso_utc: str | None = None) -> int:
    if iso_utc:
        return int(_scalar("SELECT COALESCE(SUM(total),0) FROM orders WHERE status='paid' AND paid_at >= %s", (iso_utc,)))
    return int(_scalar("SELECT COALESCE(SUM(total),0) FROM orders WHERE status='paid'"))


def get_stats() -> dict:
    now = _now_iso()
    wib_midnight = datetime.now(_WIB).replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc = wib_midnight.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    month_utc = (datetime.now() - timedelta(days=30)).isoformat()
    return {
        "users": _scalar("SELECT COUNT(*) FROM users"),
        "vip_active": _scalar("SELECT COUNT(*) FROM subscriptions WHERE is_active=1 AND plan='vip' AND expired_at > %s", (now,)),
        "trial_active": _scalar("SELECT COUNT(*) FROM subscriptions WHERE is_active=1 AND plan='trial' AND expired_at > %s", (now,)),
        "vip_expired": _scalar("SELECT COUNT(*) FROM subscriptions WHERE plan='vip' AND (is_active=0 OR expired_at <= %s)", (now,)),
        "vip_expiring": _scalar(
            "SELECT COUNT(*) FROM subscriptions WHERE is_active=1 AND plan='vip' AND expired_at > %s AND expired_at <= %s",
            (now, (datetime.now() + timedelta(days=3)).isoformat())),
        "sessions": _scalar("SELECT COUNT(*) FROM sessions"),
        "qris_saved": _scalar("SELECT COUNT(*) FROM user_qris"),
        "orders_pending": count_orders("pending"),
        "orders_verifying": count_orders("verifying"),
        "orders_paid": count_orders("paid"),
        "revenue_today": revenue_since(today_utc),
        "revenue_30d": revenue_since(month_utc),
        "revenue_total": revenue_since(None),
    }


def get_all_user_ids() -> list[int]:
    return [r[0] for r in _run("SELECT user_id FROM users", (), "all")]


def count_vip_active() -> int:
    return _scalar("SELECT COUNT(*) FROM subscriptions WHERE is_active=1 AND plan='vip' AND expired_at > %s", (_now_iso(),))


def get_vip_page(limit: int = 8, offset: int = 0) -> list[dict]:
    rows = _run(
        """
        SELECT s.user_id, u.username, u.full_name, s.paid_at, s.expired_at
        FROM subscriptions s LEFT JOIN users u ON s.user_id = u.user_id
        WHERE s.is_active=1 AND s.plan='vip' AND s.expired_at > %s
        ORDER BY s.expired_at ASC LIMIT %s OFFSET %s
        """,
        (_now_iso(), limit, offset), "all",
    )
    return [{"user_id": r[0], "username": r[1], "full_name": r[2], "paid_at": r[3], "expired_at": r[4]} for r in rows]


def get_user_profile(user_id: int) -> dict | None:
    u = _run("SELECT user_id, username, full_name, created_at, trial_used FROM users WHERE user_id=%s", (user_id,), "one")
    sub = get_subscription_info(user_id)
    if not u and not sub:
        return None
    paid = _run("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders WHERE user_id=%s AND status='paid'", (user_id,), "one")
    return {
        "user_id": user_id,
        "username": u[1] if u else None,
        "full_name": u[2] if u else None,
        "created_at": u[3] if u else None,
        "trial_used": bool(u[4]) if u else False,
        "sub": sub,   # (paid_at, expired_at, is_active, plan) | None
        "has_session": get_user_session(user_id) is not None,
        "has_qris": get_user_qris(user_id) is not None,
        "paid_orders": paid[0],
        "paid_total": int(paid[1]),
        "token": get_token(user_id),
    }


def resolve_user_id(target: str) -> int | None:
    clean = target.strip().lstrip("@")
    if clean.lstrip("-").isdigit():
        return int(clean)
    return get_user_by_username(clean)


# ── Pengingat masa aktif ───────────────────────────────────────────────────────

def get_subs_for_reminder() -> list[dict]:
    rows = _run(
        "SELECT user_id, plan, expired_at, COALESCE(reminder_stage,0) FROM subscriptions "
        "WHERE is_active=1 AND COALESCE(reminder_stage,0) < 3", (), "all",
    )
    return [{"user_id": r[0], "plan": r[1], "expired_at": r[2], "stage": r[3]} for r in rows]


def get_sync_user_ids() -> tuple[list[int], list[int]]:
    """
    Untuk sinkronisasi client dengan database (VIP bisa berubah lewat Mini App di luar proses bot).
    Return (user yang HARUS berjalan: punya session & VIP aktif, user yang HARUS berhenti: langganan sudah mati).
    """
    now = _now_iso()
    live = _run("SELECT s.user_id FROM sessions s JOIN subscriptions b ON b.user_id=s.user_id "
                "WHERE b.is_active=1 AND b.expired_at > %s", (now,), "all")
    dead = _run("SELECT user_id FROM subscriptions WHERE is_active=0 OR expired_at <= %s", (now,), "all")
    return [r[0] for r in live], [r[0] for r in dead]


def set_reminder_stage(user_id: int, stage: int) -> None:
    _run("UPDATE subscriptions SET reminder_stage=%s WHERE user_id=%s", (stage, user_id))


# ══════════════════════════════════════════════════════════════════════════════
#  Kategori Data — info database & pembersihan data tidak penting
# ══════════════════════════════════════════════════════════════════════════════

_CLEAN_LABELS = {
    "users": "Pengguna tanpa VIP/trial aktif",
    "sessions": "Session tersimpan",
    "subscriptions": "Langganan expired / dicabut / trial",
    "orders": "Riwayat pesanan",
    "related": "Pengaturan, QRIS, blacklist, auto block, token",
    "codes": "Voucher dan kode promo habis / kedaluwarsa",
}
CLEAN_KEYS = list(_CLEAN_LABELS)


def clean_label(key: str) -> str:
    return _CLEAN_LABELS[key]


def get_db_info() -> dict:
    """Ukuran database + jumlah baris tabel utama (untuk layar Data)."""
    info: dict = {"size": None}
    try:
        info["size"] = int(_run("SELECT pg_database_size(current_database())", (), "one")[0])
    except Exception:
        pass
    for t in ("users", "sessions", "subscriptions", "orders", "user_qris", "plans"):
        info[t] = _scalar(f"SELECT COUNT(*) FROM {t}")
    return info


# Tabel yang barisnya terikat ke satu user_id (kolom pemilik di elemen kedua).
_USER_TABLES = [
    ("users", "user_id"), ("sessions", "user_id"), ("subscriptions", "user_id"),
    ("orders", "user_id"), ("user_settings", "user_id"), ("user_qris", "user_id"),
    ("bc_group_blacklist", "user_id"), ("auto_block_channels", "user_id"),
    ("vip_tokens", "holder_id"),
]


def cleanup_all(dry_run: bool = False) -> dict:
    """
    Bersihkan semua data yang tidak diperlukan dalam SATU transaksi, tanpa batas waktu.

    Yang DIPERTAHANKAN: admin, user dengan VIP/trial yang masih aktif, dan user yang masih
    punya pesanan menunggu bayar/verifikasi. Selain itu (belum pernah beli, VIP expired atau
    dicabut, pemakai trial, sisa data yatim) dihapus beserta session, langganan, pesanan,
    pengaturan, QRIS, blacklist broadcast, auto block, dan token VIP-nya.
    Pesanan gagal/batal/kedaluwarsa milik semua user ikut dihapus. Voucher dan promo yang sudah
    habis atau kedaluwarsa dihapus; paket, pengaturan bot, dan blacklist channel tidak disentuh.

    Dua pengecualian agar kuota tidak bisa diakali setelah pembersihan:
    - pesanan lunas yang memakai kode promo berkuota yang masih aktif tetap disimpan
      (jumlah pemakaian promo dihitung dari tabel pesanan);
    - klaim voucher hanya dihapus bersama voucher-nya.

    dry_run=True: jalankan lalu ROLLBACK -> hanya untuk mengetahui jumlah pasti.
    Return: {kunci: jumlah baris} untuk CLEAN_KEYS, ditambah "user_ids" (daftar user yang dihapus).
    """
    from config import ADMIN_ID
    now = datetime.now().isoformat()
    conn = get_conn()
    try:
        cur = conn.cursor()
        # 1. Kumpulkan user yang boleh dihapus: semua id yang muncul di tabel mana pun,
        #    dikurangi admin, VIP/trial aktif, dan pemilik pesanan yang masih terbuka.
        universe = " UNION ".join(f"SELECT {col} AS uid FROM {t}" for t, col in _USER_TABLES)
        universe += " UNION SELECT from_id FROM vip_token_log UNION SELECT to_id FROM vip_token_log"
        cur.execute(
            f"CREATE TEMP TABLE _clean_ids ON COMMIT DROP AS SELECT uid FROM ({universe}) u "
            "WHERE uid <> %s "
            "AND uid NOT IN (SELECT user_id FROM subscriptions WHERE is_active=1 AND expired_at > %s) "
            "AND uid NOT IN (SELECT user_id FROM orders WHERE status IN ('pending','verifying'))",
            (ADMIN_ID, now))
        cur.execute("SELECT uid FROM _clean_ids")
        user_ids = [r[0] for r in cur.fetchall()]

        result = dict.fromkeys(CLEAN_KEYS, 0)

        # 2. Pesanan: gagal/batal/kedaluwarsa milik siapa pun, dan semua riwayat milik user yang dihapus
        #    (kecuali pesanan lunas yang masih menjadi hitungan kuota promo aktif).
        keep_promo = ("promo_id IN (SELECT id FROM promo_codes WHERE is_active=1 AND max_uses>0 "
                      "AND (expires_at IS NULL OR expires_at > %s))")
        cur.execute(
            "DELETE FROM orders WHERE status IN ('expired','cancelled','rejected') "
            f"OR (user_id IN (SELECT uid FROM _clean_ids) AND status NOT IN ('pending','verifying') "
            f"AND NOT COALESCE({keep_promo}, FALSE))", (now,))
        result["orders"] = cur.rowcount or 0

        # 3. Data milik user yang dihapus.
        for key, table, col in (
            ("sessions", "sessions", "user_id"),
            ("subscriptions", "subscriptions", "user_id"),
        ):
            cur.execute(f"DELETE FROM {table} WHERE {col} IN (SELECT uid FROM _clean_ids)")
            result[key] = cur.rowcount or 0
        for table, col in (("user_settings", "user_id"), ("user_qris", "user_id"),
                           ("bc_group_blacklist", "user_id"), ("auto_block_channels", "user_id"),
                           ("vip_tokens", "holder_id")):
            cur.execute(f"DELETE FROM {table} WHERE {col} IN (SELECT uid FROM _clean_ids)")
            result["related"] += cur.rowcount or 0
        cur.execute("DELETE FROM vip_token_log WHERE from_id IN (SELECT uid FROM _clean_ids) "
                    "AND to_id IN (SELECT uid FROM _clean_ids)")
        result["related"] += cur.rowcount or 0
        cur.execute("DELETE FROM users WHERE user_id IN (SELECT uid FROM _clean_ids)")
        result["users"] = cur.rowcount or 0

        # 4. Voucher habis/kedaluwarsa (beserta klaimnya) dan promo kedaluwarsa.
        cur.execute(
            "DELETE FROM vouchers v WHERE (v.expires_at IS NOT NULL AND v.expires_at <= %s) "
            "OR (v.max_claims > 0 AND (SELECT COUNT(*) FROM voucher_claims c WHERE c.voucher_id=v.id) >= v.max_claims)",
            (now,))
        result["codes"] += cur.rowcount or 0
        cur.execute("DELETE FROM voucher_claims WHERE voucher_id NOT IN (SELECT id FROM vouchers)")
        result["related"] += cur.rowcount or 0
        cur.execute("DELETE FROM promo_codes WHERE expires_at IS NOT NULL AND expires_at <= %s", (now,))
        result["codes"] += cur.rowcount or 0

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        result["user_ids"] = user_ids
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def vacuum_db() -> None:
    """Rapikan ruang setelah penghapusan (VACUUM tidak boleh di dalam transaksi)."""
    conn = get_conn()
    try:
        conn.autocommit = True
        conn.cursor().execute("VACUUM ANALYZE")
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Token VIP — pindahkan VIP ke akun lain (maks 3x), diterbitkan tiap pembelian
# ══════════════════════════════════════════════════════════════════════════════

def _token(r) -> dict:
    return {"token": r[0], "holder_id": r[1], "uses": r[2], "max_uses": r[3]}


def get_token(user_id: int) -> dict | None:
    """Token yang saat ini dipegang user (akun pemegang VIP)."""
    r = _run("SELECT token, holder_id, uses, max_uses FROM vip_tokens WHERE holder_id=%s", (user_id,), "one")
    return _token(r) if r else None


def issue_token(user_id: int) -> dict:
    """Terbitkan kode token acak BARU untuk user dan reset pemakaian ke 0 (token lama hangus)."""
    now = _now_iso()
    for _ in range(5):
        try:
            _run(
                """
                INSERT INTO vip_tokens (token, holder_id, uses, max_uses, created_at, updated_at)
                VALUES (%s,%s,0,%s,%s,%s)
                ON CONFLICT(holder_id) DO UPDATE SET token=EXCLUDED.token, uses=0,
                    max_uses=EXCLUDED.max_uses, created_at=EXCLUDED.created_at, updated_at=EXCLUDED.updated_at
                """,
                (generate_token(), user_id, MAX_TOKEN_USES, now, now),
            )
            return get_token(user_id)
        except psycopg2.errors.UniqueViolation:
            continue                       # kode kebetulan kembar, buat ulang
    raise RuntimeError("Gagal membuat token unik.")


def ensure_token(user_id: int) -> dict | None:
    """Token user; dibuat bila belum ada DAN user punya VIP berbayar aktif (mis. VIP lama / hasil gift)."""
    tok = get_token(user_id)
    if tok:
        return tok
    row = get_subscription_info(user_id)          # (paid_at, expired_at, is_active, plan)
    if row and row[2] and row[3] == "vip" and datetime.now() < datetime.fromisoformat(row[1]):
        return issue_token(user_id)
    return None


def transfer_vip_by_token(code: str, to_id: int) -> dict:
    """
    Pindahkan sisa VIP dari pemegang token ke akun to_id, dalam SATU transaksi.
    Token ikut berpindah ke akun baru (kode sama, pemakaian +1) sehingga bisa dipindah lagi sampai batas.
    Return {"ok": True, ...} atau {"ok": False, "error": invalid|same|limit|inactive|target_active}.
    """
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT token, holder_id, uses, max_uses FROM vip_tokens WHERE token=%s FOR UPDATE", (code,))
        row = c.fetchone()
        if not row:
            return {"ok": False, "error": "invalid"}
        token, holder, uses, max_uses = row
        if holder == to_id:
            return {"ok": False, "error": "same"}
        if uses >= max_uses:
            return {"ok": False, "error": "limit"}
        now = datetime.now()

        c.execute("SELECT paid_at, expired_at, is_active, plan FROM subscriptions WHERE user_id=%s FOR UPDATE", (holder,))
        src = c.fetchone()
        try:
            src_exp = datetime.fromisoformat(src[1]) if src else None
        except Exception:
            src_exp = None
        if not src or not src[2] or src[3] != "vip" or not src_exp or src_exp <= now:
            return {"ok": False, "error": "inactive"}

        c.execute("SELECT expired_at, is_active, plan FROM subscriptions WHERE user_id=%s FOR UPDATE", (to_id,))
        tgt = c.fetchone()
        if tgt and tgt[1] and tgt[2] == "vip":
            try:
                if datetime.fromisoformat(tgt[0]) > now:
                    return {"ok": False, "error": "target_active"}
            except Exception:
                pass

        # Akun lama dinonaktifkan, akun baru menerima sisa masa VIP yang persis sama.
        c.execute("UPDATE subscriptions SET is_active=0, expired_at=%s WHERE user_id=%s", (now.isoformat(), holder))
        c.execute(
            """
            INSERT INTO subscriptions (user_id, plan, paid_at, expired_at, is_active, reminder_stage)
            VALUES (%s,'vip',%s,%s,1,0)
            ON CONFLICT(user_id) DO UPDATE SET paid_at=EXCLUDED.paid_at, expired_at=EXCLUDED.expired_at,
                is_active=1, plan='vip', reminder_stage=0
            """,
            (to_id, src[0], src_exp.isoformat()),
        )
        c.execute("DELETE FROM vip_tokens WHERE holder_id=%s AND token<>%s", (to_id, token))   # token lama akun baru
        c.execute("UPDATE vip_tokens SET holder_id=%s, uses=uses+1, updated_at=%s WHERE token=%s",
                  (to_id, now.isoformat(), token))
        c.execute("INSERT INTO vip_token_log (token, from_id, to_id, created_at) VALUES (%s,%s,%s,%s)",
                  (token, holder, to_id, now.isoformat()))
        conn.commit()
        return {"ok": True, "token": token, "from_id": holder, "to_id": to_id, "expired": src_exp,
                "uses": uses + 1, "max_uses": max_uses}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_token_log(user_id: int, limit: int = 3) -> list[dict]:
    rows = _run(
        "SELECT from_id, to_id, created_at FROM vip_token_log WHERE from_id=%s OR to_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, user_id, limit), "all",
    )
    return [{"from_id": r[0], "to_id": r[1], "created_at": r[2]} for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
#  Kode promo (diskon 1-100%)
# ══════════════════════════════════════════════════════════════════════════════

_PROMO_COLS = "id, code, percent, max_uses, expires_at, is_active"
# Pesanan yang memakan kuota. Batal/kedaluwarsa/ditolak otomatis membebaskan kuota.
_PROMO_COUNTED = "('pending','verifying','paid','revoked')"


def _promo(r) -> dict:
    d = {"id": r[0], "code": r[1], "percent": r[2], "max_uses": r[3], "expires_at": r[4], "is_active": bool(r[5])}
    if len(r) > 6:
        d["used"] = r[6]
    return d


def _promo_counts(c, promo_id: int, user_id: int) -> tuple[int, int]:
    c.execute(
        f"SELECT COUNT(*), COUNT(*) FILTER (WHERE user_id=%s) FROM orders "
        f"WHERE promo_id=%s AND status IN {_PROMO_COUNTED}", (user_id, promo_id))
    r = c.fetchone()
    return r[0], r[1]


_PROMO_WITH_USED = (f"SELECT {_PROMO_COLS}, (SELECT COUNT(*) FROM orders o WHERE o.promo_id=promo_codes.id "
                    f"AND o.status IN {_PROMO_COUNTED}) FROM promo_codes")


def add_promo(code: str, percent: int, max_uses: int = 0, expires_at: str | None = None) -> int | None:
    """Return id promo, atau None bila kode sudah ada. max_uses=0 berarti tanpa batas."""
    try:
        return _run(
            "INSERT INTO promo_codes (code, percent, max_uses, expires_at, is_active, created_at) "
            "VALUES (%s,%s,%s,%s,1,%s) RETURNING id",
            (code, percent, max_uses, expires_at, _now_iso()), "one")[0]
    except psycopg2.errors.UniqueViolation:
        return None


def get_promo(promo_id: int) -> dict | None:
    r = _run(_PROMO_WITH_USED + " WHERE id=%s", (promo_id,), "one")
    return _promo(r) if r else None


def get_promo_by_code(code: str) -> dict | None:
    r = _run(f"SELECT {_PROMO_COLS} FROM promo_codes WHERE code=%s", (code,), "one")
    return _promo(r) if r else None


def get_promos(limit: int = 8, offset: int = 0) -> list[dict]:
    return [_promo(r) for r in _run(_PROMO_WITH_USED + " ORDER BY id DESC LIMIT %s OFFSET %s", (limit, offset), "all")]


def count_promos() -> int:
    return _scalar("SELECT COUNT(*) FROM promo_codes")


def set_promo_active(promo_id: int, active: bool) -> None:
    _run("UPDATE promo_codes SET is_active=%s WHERE id=%s", (1 if active else 0, promo_id))


def delete_promo(promo_id: int) -> bool:
    return (_run("DELETE FROM promo_codes WHERE id=%s", (promo_id,), "rowcount") or 0) > 0


def check_promo(code: str, user_id: int) -> dict:
    """Validasi kode promo untuk user. Return promo (dict) atau raise CodeError."""
    p = get_promo_by_code(code)
    used = user_used = 0
    if p:
        row = _run(
            f"SELECT COUNT(*), COUNT(*) FILTER (WHERE user_id=%s) FROM orders "
            f"WHERE promo_id=%s AND status IN {_PROMO_COUNTED}", (user_id, p["id"]), "one")
        used, user_used = row[0], row[1]
    problem = promo_problem(p, used, user_used, datetime.now())
    if problem:
        raise problem
    return p


# ══════════════════════════════════════════════════════════════════════════════
#  Voucher klaim VIP
# ══════════════════════════════════════════════════════════════════════════════

_VCH_COLS = "id, code, days, max_claims, expires_at, is_active"
_VCH_WITH_CLAIMED = (f"SELECT {_VCH_COLS}, (SELECT COUNT(*) FROM voucher_claims vc WHERE vc.voucher_id=vouchers.id) "
                     "FROM vouchers")


def _voucher(r) -> dict:
    d = {"id": r[0], "code": r[1], "days": r[2], "max_claims": r[3], "expires_at": r[4], "is_active": bool(r[5])}
    if len(r) > 6:
        d["claimed"] = r[6]
    return d


def add_voucher(code: str, days: int, max_claims: int = 1, expires_at: str | None = None) -> int | None:
    """Return id voucher, atau None bila kode sudah ada. max_claims=0 berarti tanpa batas."""
    try:
        return _run(
            "INSERT INTO vouchers (code, days, max_claims, expires_at, is_active, created_at) "
            "VALUES (%s,%s,%s,%s,1,%s) RETURNING id",
            (code, days, max_claims, expires_at, _now_iso()), "one")[0]
    except psycopg2.errors.UniqueViolation:
        return None


def add_vouchers_bulk(days: int, count: int, expires_at: str | None = None) -> list[str]:
    """Buat `count` voucher sekali-pakai dengan kode acak, dalam satu transaksi."""
    codes: list[str] = []
    conn = get_conn()
    try:
        c = conn.cursor()
        now = _now_iso()
        while len(codes) < count:
            code = generate_code(10)
            c.execute(
                "INSERT INTO vouchers (code, days, max_claims, expires_at, is_active, created_at) "
                "VALUES (%s,%s,1,%s,1,%s) ON CONFLICT(code) DO NOTHING RETURNING id",
                (code, days, expires_at, now))
            if c.fetchone():
                codes.append(code)
        conn.commit()
        return codes
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_voucher(voucher_id: int) -> dict | None:
    r = _run(_VCH_WITH_CLAIMED + " WHERE id=%s", (voucher_id,), "one")
    return _voucher(r) if r else None


def get_vouchers(limit: int = 8, offset: int = 0) -> list[dict]:
    return [_voucher(r) for r in _run(_VCH_WITH_CLAIMED + " ORDER BY id DESC LIMIT %s OFFSET %s", (limit, offset), "all")]


def count_vouchers() -> int:
    return _scalar("SELECT COUNT(*) FROM vouchers")


def get_voucher_claims(voucher_id: int, limit: int = 5) -> list[dict]:
    rows = _run(
        "SELECT vc.user_id, u.username, u.full_name, vc.claimed_at FROM voucher_claims vc "
        "LEFT JOIN users u ON u.user_id = vc.user_id WHERE vc.voucher_id=%s ORDER BY vc.id DESC LIMIT %s",
        (voucher_id, limit), "all")
    return [{"user_id": r[0], "username": r[1], "full_name": r[2], "claimed_at": r[3]} for r in rows]


def set_voucher_active(voucher_id: int, active: bool) -> None:
    _run("UPDATE vouchers SET is_active=%s WHERE id=%s", (1 if active else 0, voucher_id))


def delete_voucher(voucher_id: int) -> bool:
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM voucher_claims WHERE voucher_id=%s", (voucher_id,))
        c.execute("DELETE FROM vouchers WHERE id=%s", (voucher_id,))
        deleted = c.rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()


def claim_voucher(code: str, user_id: int) -> dict:
    """
    Klaim voucher: cek, catat klaim, dan tambah masa VIP dalam SATU transaksi
    (baris voucher dikunci, jadi kuota tidak bisa terlampaui). Raise CodeError bila ditolak.
    Setelah berhasil, user mendapat token baru. Return {"code", "days", "expired", "token"}.
    """
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(f"SELECT {_VCH_COLS} FROM vouchers WHERE code=%s FOR UPDATE", (code,))
        r = c.fetchone()
        if not r or not r[5]:
            raise CodeError("Kode voucher tidak ditemukan atau sudah tidak aktif.", not_found=True)
        vid, vcode, days, max_claims, expires_at, _active = r
        if expires_at and datetime.fromisoformat(expires_at) <= datetime.now():
            raise CodeError("Kode voucher sudah kedaluwarsa.")
        c.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE user_id=%s) FROM voucher_claims WHERE voucher_id=%s",
                  (user_id, vid))
        total, mine = c.fetchone()
        if mine:
            raise CodeError("Kamu sudah pernah mengklaim voucher ini.")
        if max_claims and total >= max_claims:
            raise CodeError("Voucher ini sudah habis diklaim.")
        c.execute("INSERT INTO voucher_claims (voucher_id, user_id, claimed_at) VALUES (%s,%s,%s)",
                  (vid, user_id, _now_iso()))
        expired = _extend_sub_cur(c, user_id, days)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"code": vcode, "days": days, "expired": expired, "token": issue_token(user_id)}


# ── Rich Post: daftar channel/grup tujuan ─────────────────────────────────────
MAX_RICH_TARGETS = 20


def get_rich_targets(user_id: int) -> list[dict]:
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT chat_id, title, chat_type FROM rich_targets WHERE user_id=%s ORDER BY id", (user_id,))
    rows = cur.fetchall(); conn.close()
    return [{"chat_id": r[0], "title": r[1] or str(r[0]), "chat_type": r[2] or ""} for r in rows]


def add_rich_target(user_id: int, chat_id: int, title: str, chat_type: str) -> bool:
    """False bila daftar sudah penuh (tujuan baru). Tujuan yang sudah ada hanya diperbarui namanya."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM rich_targets WHERE user_id=%s AND chat_id<>%s", (user_id, chat_id))
    if cur.fetchone()[0] >= MAX_RICH_TARGETS:
        conn.close(); return False
    cur.execute(
        """
        INSERT INTO rich_targets (user_id, chat_id, title, chat_type, added_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id, chat_id) DO UPDATE SET title=EXCLUDED.title, chat_type=EXCLUDED.chat_type
        """,
        (user_id, chat_id, title, chat_type, _now_iso()),
    )
    conn.commit(); conn.close()
    return True


def delete_rich_target(user_id: int, chat_id: int) -> None:
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM rich_targets WHERE user_id=%s AND chat_id=%s", (user_id, chat_id))
    conn.commit(); conn.close()
