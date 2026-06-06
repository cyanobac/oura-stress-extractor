"""Per-IP daily quota backed by SQLite.

The public box has no auth, so this stops a single IP/bot from monopolizing the
free OCR service. It counts only *successful* extractions (the caller decides
when to `record`), in a rolling window, and persists to a SQLite file so the
limit survives container restarts and redeploys.

Each function opens its own short-lived connection, so the helpers are safe to
call from worker threads (e.g. via `run_in_threadpool`) without sharing a
connection across threads.
"""
import os
import sqlite3
import time

# Read config lazily (per call) so tests can point RATE_LIMIT_DB at a tmp file
# and tweak limits via env without re-importing the module.
_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "ratelimit.db")


def db_path() -> str:
    return os.environ.get("RATE_LIMIT_DB", _DEFAULT_DB)


def max_hits() -> int:
    """Allowed successful extractions per window. 0 disables the limiter."""
    return int(os.environ.get("RATE_LIMIT_MAX", "10"))


def window_seconds() -> int:
    return int(float(os.environ.get("RATE_LIMIT_WINDOW_HOURS", "24")) * 3600)


def enabled() -> bool:
    return max_hits() > 0


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS hits (ip TEXT NOT NULL, ts REAL NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hits_ip_ts ON hits (ip, ts)")
    return conn


def count_recent(ip: str, window_s: int | None = None) -> int:
    """Prune this ip's expired hits, then count what remains in the window."""
    window_s = window_seconds() if window_s is None else window_s
    cutoff = time.time() - window_s
    with _connect() as conn:
        conn.execute("DELETE FROM hits WHERE ip = ? AND ts < ?", (ip, cutoff))
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM hits WHERE ip = ? AND ts >= ?", (ip, cutoff)
        ).fetchone()
    return n


def record(ip: str) -> None:
    """Record one successful extraction for this ip."""
    with _connect() as conn:
        conn.execute("INSERT INTO hits (ip, ts) VALUES (?, ?)", (ip, time.time()))


def seconds_until_reset(ip: str, window_s: int | None = None) -> int:
    """Seconds until this ip's oldest in-window hit expires (for Retry-After)."""
    window_s = window_seconds() if window_s is None else window_s
    cutoff = time.time() - window_s
    with _connect() as conn:
        row = conn.execute(
            "SELECT MIN(ts) FROM hits WHERE ip = ? AND ts >= ?", (ip, cutoff)
        ).fetchone()
    oldest = row[0] if row else None
    if oldest is None:
        return 0
    return max(1, int(oldest + window_s - time.time()))
