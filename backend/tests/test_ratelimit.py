"""Unit tests for the SQLite per-IP rate limiter."""
import time

from app import ratelimit


def test_record_and_count():
    assert ratelimit.count_recent("1.2.3.4") == 0
    ratelimit.record("1.2.3.4")
    ratelimit.record("1.2.3.4")
    assert ratelimit.count_recent("1.2.3.4") == 2
    # A different IP has its own count.
    assert ratelimit.count_recent("5.6.7.8") == 0


def test_window_prunes_old_hits(monkeypatch):
    # Use a tiny window so we can age a hit out of it.
    monkeypatch.setenv("RATE_LIMIT_WINDOW_HOURS", str(1 / 3600))  # 1 second
    ratelimit.record("9.9.9.9")
    assert ratelimit.count_recent("9.9.9.9") == 1
    time.sleep(1.1)
    assert ratelimit.count_recent("9.9.9.9") == 0


def test_seconds_until_reset_within_window():
    ratelimit.record("4.4.4.4")
    retry = ratelimit.seconds_until_reset("4.4.4.4")
    # Default 24h window; just-recorded hit expires in ~24h, never 0.
    assert 0 < retry <= 24 * 3600


def test_seconds_until_reset_no_hits():
    assert ratelimit.seconds_until_reset("0.0.0.0") == 0


def test_enabled_toggle(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_MAX", "0")
    assert ratelimit.enabled() is False
    monkeypatch.setenv("RATE_LIMIT_MAX", "10")
    assert ratelimit.enabled() is True
    assert ratelimit.max_hits() == 10
