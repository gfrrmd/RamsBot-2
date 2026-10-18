import asyncio
import gzip


def _split_sql_statements(sql: str) -> list[str]:
    """Pecah file SQL menjadi statement. Sadar tanda kutip: ';' / '(' di dalam string aman."""
    stmts: list[str] = []
    buf: list[str] = []
    in_quote = False
    at_line_start = True
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if not in_quote and at_line_start and sql.startswith("--", i):   # baris komentar
            j = sql.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if ch == "'":
            in_quote = not in_quote       # '' (escape) = toggle dua kali -> tetap benar
        if ch == ";" and not in_quote:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        at_line_start = ch == "\n" or (at_line_start and ch in " \t")
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def build_backup_sql() -> tuple[bytes, dict]:
    """Dump seluruh tabel public ke SQL. Return (bytes, {tabel: jumlah_baris})."""
    from database import get_conn
    conn = get_conn(); cur = conn.cursor()
    row_counts: dict = {}
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]
    lines = []
    for table in tables:
        cur.execute("""
            SELECT column_name, data_type, character_maximum_length, is_nullable, column_default
            FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table,))
        col_defs = []
        for col_name, data_type, char_max_len, is_nullable, col_default in cur.fetchall():
            if data_type in ("character varying", "varchar"):
                type_str = f"VARCHAR({char_max_len})" if char_max_len else "TEXT"
            elif data_type == "character":
                type_str = f"CHAR({char_max_len})" if char_max_len else "CHAR"
            else:
                type_str = data_type.upper()
            col_defs.append(f"    {col_name} {type_str}{'' if is_nullable == 'YES' else ' NOT NULL'}{f' DEFAULT {col_default}' if col_default else ''}")
        lines += [f"-- Table: {table}", f"CREATE TABLE IF NOT EXISTS {table} (", ",\n".join(col_defs), ");", ""]
        cur.execute(f'SELECT * FROM "{table}"')
        rows = cur.fetchall(); col_names = [desc[0] for desc in cur.description]
        row_counts[table] = len(rows)
        for row in rows:
            vals = ", ".join("'" + str(v).replace("'", "''") + "'" if v is not None else "NULL" for v in row)
            lines.append(f"INSERT INTO {table} ({', '.join(col_names)}) VALUES ({vals}) ON CONFLICT DO NOTHING;")
        lines.append("")
    conn.close()
    return "\n".join(lines).encode("utf-8"), row_counts


async def _do_backup(context=None) -> bytes:
    """Dipertahankan untuk kompatibilitas: backup manual -> bytes SQL."""
    sql_bytes, _ = await asyncio.to_thread(build_backup_sql)
    return sql_bytes


def maybe_gunzip(data: bytes) -> bytes:
    """Restore menerima .sql biasa maupun .sql.gz (dideteksi dari magic bytes)."""
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def fix_sequences(conn) -> None:
    """Setelah restore, sinkronkan sequence SERIAL agar INSERT berikutnya tidak bentrok ID."""
    cur = conn.cursor()
    cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_default LIKE 'nextval(%'")
    for table, col in cur.fetchall():
        try:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('\"{table}\"', '{col}'), "
                f"COALESCE((SELECT MAX(\"{col}\") FROM \"{table}\"), 0) + 1, false)"
            )
        except Exception as e:
            print(f"[restore] gagal sinkron sequence {table}.{col}: {e}")
            conn.rollback()
    conn.commit()
