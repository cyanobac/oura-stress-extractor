"""Tests for the vendored extraction core and the /api/extract endpoint.

The golden test pins the core's output to the daystar CLI's known-good result
for the 2026-02-10 sample, so the vendored copy can't silently drift.
"""
import datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.extractor.core import (
    ExtractionError,
    decode_image,
    extract_from_array,
    validate_dimensions,
)
from app.main import app

MASK_PATH = str(Path(__file__).parents[1] / "app" / "extractor" / "mask_scaled.png")
SAMPLE_DATE = datetime.date(2026, 2, 10)


# ---- core ----------------------------------------------------------------

def test_golden_matches_daystar_cli(sample_png_bytes, golden_rows):
    img = decode_image(sample_png_bytes)
    result = extract_from_array(img, MASK_PATH, SAMPLE_DATE)

    got = [(p["timestamp"].replace("T", " "), p["zone"]) for p in result["points"]]
    assert got == golden_rows


def test_decode_rejects_garbage():
    with pytest.raises(ExtractionError):
        decode_image(b"not an image")


def test_validate_dimensions_accepts_expected():
    validate_dimensions(np.zeros((1136, 640, 3), np.uint8))  # should not raise


def test_validate_dimensions_rejects_wrong_size():
    with pytest.raises(ExtractionError):
        validate_dimensions(np.zeros((800, 600, 3), np.uint8))


# ---- API -----------------------------------------------------------------

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_extract_endpoint_returns_points(sample_png_bytes, golden_rows):
    r = client.post(
        "/api/extract",
        files={"file": ("chart.png", sample_png_bytes, "image/png")},
        data={"date": "2026-02-10"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["points"]) == len(golden_rows)
    assert body["meta"]["reference_date"] == "2026-02-10"
    assert "annotated_png" not in body


def test_extract_endpoint_includes_image_when_requested(sample_png_bytes):
    r = client.post(
        "/api/extract",
        files={"file": ("chart.png", sample_png_bytes, "image/png")},
        data={"date": "2026-02-10", "include_image": "true"},
    )
    assert r.status_code == 200
    assert r.json()["annotated_png"]


def test_extract_endpoint_rejects_bad_date(sample_png_bytes):
    r = client.post(
        "/api/extract",
        files={"file": ("chart.png", sample_png_bytes, "image/png")},
        data={"date": "10-02-2026"},
    )
    assert r.status_code == 422


def test_extract_endpoint_rejects_wrong_size():
    # A valid 1x1 PNG that fails the dimension check.
    import cv2

    ok, buf = cv2.imencode(".png", np.zeros((10, 10, 3), np.uint8))
    assert ok
    r = client.post(
        "/api/extract",
        files={"file": ("tiny.png", buf.tobytes(), "image/png")},
        data={"date": "2026-02-10"},
    )
    assert r.status_code == 422


def test_extract_endpoint_sheds_load_when_busy(sample_png_bytes, monkeypatch):
    # With the in-flight count already at the limit, a new request is rejected
    # fast (503 + Retry-After) before any OCR runs, rather than queueing.
    from app import routes

    monkeypatch.setattr(routes, "_inflight", routes._MAX_INFLIGHT)
    r = client.post(
        "/api/extract",
        files={"file": ("chart.png", sample_png_bytes, "image/png")},
        data={"date": "2026-02-10"},
    )
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "60"


def test_extract_endpoint_rejects_oversized():
    # Bodies over the 1 MB cap are rejected before any decode/OCR.
    from app import routes

    blob = b"\x00" * (routes.MAX_UPLOAD_BYTES + 1)
    r = client.post(
        "/api/extract",
        files={"file": ("big.png", blob, "image/png")},
        data={"date": "2026-02-10"},
    )
    assert r.status_code == 413


def test_extract_endpoint_times_out(sample_png_bytes, monkeypatch):
    # A near-zero timeout fires before OCR finishes → 504, not a hung request.
    from app import routes

    monkeypatch.setattr(routes, "_EXTRACT_TIMEOUT", 0.0001)
    r = client.post(
        "/api/extract",
        files={"file": ("chart.png", sample_png_bytes, "image/png")},
        data={"date": "2026-02-10"},
    )
    assert r.status_code == 504


def test_extract_endpoint_enforces_daily_limit(sample_png_bytes):
    # Pre-seed the quota for the TestClient's IP so the limit is hit before any
    # OCR runs, then assert the next request is rejected with 429 + Retry-After.
    from app import ratelimit

    for _ in range(ratelimit.max_hits()):
        ratelimit.record("testclient")

    r = client.post(
        "/api/extract",
        files={"file": ("chart.png", sample_png_bytes, "image/png")},
        data={"date": "2026-02-10"},
    )
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert "github.com/cyanobac/oura-stress-extractor" in r.json()["detail"]
