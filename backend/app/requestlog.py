"""Durable request log backed by SQLite.

The public box has no auth, so a simple, durable trail of every API request is
worth keeping for usage patterns, performance, and abuse detection. One row per
request (served *or* rejected), with the outcome status.

Raw client IPs are never stored. Each IP is hashed with a server-side salt
(SHA-256) so repeat visitors can still be correlated without keeping PII. The
salt is read from REQUEST_LOG_SALT and **must stay constant across restarts**
for that correlation to hold — a random per-boot salt would make every redeploy
look like all-new visitors. The salt never leaves the server.

Like ratelimit.py, each call opens its own short-lived connection, so the
helpers are safe to call from worker threads (e.g. via run_in_threadpool)
without sharing a connection across threads.
"""
import hashlib
import os
import sqlite3
from datetime import datetime, timezone

# Read config lazily (per call) so tests can point REQUEST_LOG_DB at a tmp file
# and tweak the salt via env without re-importing the module.
_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "requests.db")


def db_path() -> str:
    return os.environ.get("REQUEST_LOG_DB", _DEFAULT_DB)


def enabled() -> bool:
    """Logging is on unless explicitly disabled with REQUEST_LOG=0."""
    return os.environ.get("REQUEST_LOG", "1") != "0"


def _salt() -> str:
    return os.environ.get("REQUEST_LOG_SALT", "")


def hash_ip(ip: str) -> str:
    """SHA-256(salt + ip) as hex. Stable for a given salt; stores no raw IP."""
    return hashlib.sha256((_salt() + ip).encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS request_log ("
        "id INTEGER PRIMARY KEY, "
        "ts TEXT NOT NULL, "             # ISO8601 UTC
        "ip_hash TEXT NOT NULL, "        # SHA256(salt + ip)
        "processing_ms INTEGER NOT NULL, "
        "status INTEGER NOT NULL, "      # HTTP status returned
        "success INTEGER NOT NULL, "     # 0/1 (status < 400)
        "error TEXT)"                    # nullable detail for failures
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_request_log_ts ON request_log (ts)")
    return conn


def log(ip: str, processing_ms: int, status: int, error: str | None = None) -> None:
    """Append one request record.

    Callers wrap this in try/except: a logging failure must never break the
    request path, so this raising is non-fatal by convention at the call site.
    """
    ts = datetime.now(timezone.utc).isoformat()
    success = 1 if status < 400 else 0
    with _connect() as conn:
        conn.execute(
            "INSERT INTO request_log "
            "(ts, ip_hash, processing_ms, status, success, error) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, hash_ip(ip), processing_ms, status, success, error),
        )
