"""Unit tests for the SQLite request log and its dump CLI."""
import sqlite3

from app import logdump, requestlog


def test_hash_is_stable_and_salted(monkeypatch):
    monkeypatch.setenv("REQUEST_LOG_SALT", "salt-one")
    h = requestlog.hash_ip("1.2.3.4")
    # Stable for the same salt+ip, and stores no raw IP.
    assert h == requestlog.hash_ip("1.2.3.4")
    assert "1.2.3.4" not in h
    # A different salt yields a different hash for the same IP.
    monkeypatch.setenv("REQUEST_LOG_SALT", "salt-two")
    assert requestlog.hash_ip("1.2.3.4") != h


def test_log_writes_rows():
    requestlog.log("1.2.3.4", 123, 200)
    requestlog.log("1.2.3.4", 50, 422, "bad image")
    with sqlite3.connect(requestlog.db_path()) as conn:
        rows = conn.execute(
            "SELECT processing_ms, status, success, error "
            "FROM request_log ORDER BY id"
        ).fetchall()
    assert rows[0] == (123, 200, 1, None)
    assert rows[1] == (50, 422, 0, "bad image")


def test_enabled_toggle(monkeypatch):
    monkeypatch.delenv("REQUEST_LOG", raising=False)
    assert requestlog.enabled() is True
    monkeypatch.setenv("REQUEST_LOG", "0")
    assert requestlog.enabled() is False


def test_logdump_emits_csv_newest_first(capsys):
    requestlog.log("1.1.1.1", 10, 200)
    requestlog.log("2.2.2.2", 20, 500, "boom")
    rc = logdump.main([])
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "id,ts,ip_hash,processing_ms,status,success,error"
    # Newest first: the 500 row precedes the 200 row.
    assert ",500," in out[1]
    assert ",200," in out[2]


def test_logdump_limit(capsys):
    for _ in range(3):
        requestlog.log("9.9.9.9", 5, 200)
    rc = logdump.main(["--limit", "1"])
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2  # header + one row
