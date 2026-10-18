from datetime import datetime, timedelta, timezone

import psycopg2

from config import DATABASE_URL


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
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
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

def extend_subscription(user_id: int, days: int) -> datetime:
    """
    Tambah masa VIP. Jika VIP masih aktif, hari ditambahkan di atas tanggal expired
    saat ini (perpanjang). Jika belum/sudah habis/trial, hitung dari sekarang.
    """
    now = datetime.now()
    row = _run("SELECT paid_at, expired_at, is_active, plan FROM subscriptions WHERE user_id=%s", (user_id,), "one")
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
    _run(
        """
        INSERT INTO subscriptions (user_id, plan, paid_at, expired_at, is_active, reminder_stage)
        VALUES (%s,'vip',%s,%s,1,0)
        ON CONFLICT(user_id) DO UPDATE SET paid_at=EXCLUDED.paid_at, expired_at=EXCLUDED.expired_at,
            is_active=1, plan='vip', reminder_stage=0
        """,
        (user_id, paid_at, expired.isoformat()),
    )
    return expired


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
               "qris_payload, proof_file_id, created_at, updated_at, paid_at, handled_by")
_ORDER_KEYS = [k.strip() for k in _ORDER_COLS.split(",")]


def _order(r) -> dict:
    return dict(zip(_ORDER_KEYS, r))


def active_order_totals() -> set[int]:
    rows = _run("SELECT total FROM orders WHERE status IN ('pending','verifying')", (), "all")
    return {r[0] for r in rows}


def create_order(user_id: int, plan: dict, unique_code: int, total: int, qris_payload: str) -> int:
    now = _now_iso()
    row = _run(
        """
        INSERT INTO orders (user_id, plan_id, plan_name, days, base_price, unique_code, total,
                            status, qris_payload, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s) RETURNING id
        """,
        (user_id, plan["id"], plan["name"], plan["days"], plan["price"], unique_code, total, qris_payload, now, now),
        "one",
    )
    return row[0]


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


def set_order_proof(order_id: int, file_id: str) -> bool:
    return (_run(
        "UPDATE orders SET proof_file_id=%s, status='verifying', updated_at=%s "
        "WHERE id=%s AND status IN ('pending','verifying')",
        (file_id, _now_iso(), order_id), "rowcount",
    ) or 0) > 0


def update_order_status(order_id: int, status: str, only_from: tuple = (), handled_by: int | None = None) -> bool:
    sql = "UPDATE orders SET status=%s, updated_at=%s, handled_by=COALESCE(%s, handled_by) WHERE id=%s"
    params: list = [status, _now_iso(), handled_by, order_id]
    if only_from:
        sql += " AND status IN (" + ",".join(["%s"] * len(only_from)) + ")"
        params += list(only_from)
    return (_run(sql, tuple(params), "rowcount") or 0) > 0


def approve_order(order_id: int, admin_id: int) -> dict | None:
    """
    Setujui order secara atomik (anti double-approve) lalu perpanjang VIP.
    Return order (dengan key 'new_expired') atau None jika sudah diproses.
    """
    now = _now_iso()
    changed = _run(
        "UPDATE orders SET status='paid', paid_at=%s, updated_at=%s, handled_by=%s "
        "WHERE id=%s AND status IN ('pending','verifying','expired')",
        (now, now, admin_id, order_id), "rowcount",
    )
    if not changed:
        return None
    order = get_order(order_id)
    order["new_expired"] = extend_subscription(order["user_id"], order["days"])
    return order


def list_orders(status: str | tuple | None = None, limit: int = 8, offset: int = 0) -> list[dict]:
    sql = f"SELECT {_ORDER_COLS} FROM orders"
    params: list = []
    if status:
        statuses = (status,) if isinstance(status, str) else tuple(status)
        sql += " WHERE status IN (" + ",".join(["%s"] * len(statuses)) + ")"
        params += list(statuses)
    sql += " ORDER BY id DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    return [_order(r) for r in _run(sql, tuple(params), "all")]


def count_orders(status: str | tuple | None = None) -> int:
    sql = "SELECT COUNT(*) FROM orders"
    params: list = []
    if status:
        statuses = (status,) if isinstance(status, str) else tuple(status)
        sql += " WHERE status IN (" + ",".join(["%s"] * len(statuses)) + ")"
        params += list(statuses)
    return _run(sql, tuple(params), "one")[0]


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


def set_reminder_stage(user_id: int, stage: int) -> None:
    _run("UPDATE subscriptions SET reminder_stage=%s WHERE user_id=%s", (stage, user_id))
