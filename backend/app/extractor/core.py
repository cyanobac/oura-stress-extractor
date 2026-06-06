"""Pure stress-chart extraction: image array in, structured data out.

This is the web-facing core, decoupled from the filesystem, the CLI, and any
date-from-filename assumptions. The original daystar CLI built timestamps from a
date embedded in the screenshot's filename; here the caller passes an explicit
reference_date (entered by the user in the web form).

The pixel geometry (dot x-range, crop bounds, OCR regions, the bundled mask) all
assume a single screenshot resolution. validate_dimensions() guards against
uploads that don't match, so we fail loudly instead of emitting a wrong table.
"""
from datetime import timedelta

import cv2
import numpy as np

from .image_helpers import preprocess_array, detect_dots, zone_for_y, detect_gaps
from .ocr_helpers import extract_times_from_chart
from .visualization_helpers import create_visualization

# ------------------------------------------------------------
# CONFIGURATION (carried over verbatim from extractor/extract_x_auto.py
# so web results match the CLI)
# ------------------------------------------------------------

# Expected screenshot resolution (width, height). Oura "Daytime Stress" screen
# captured on an iPhone SE/8-class device. Everything below assumes this size.
EXPECTED_WIDTH = 640
EXPECTED_HEIGHT = 1136
DIMENSION_TOLERANCE = 4  # px of slack on each axis

# Fixed x-positions for first and last possible dots
FIRST_DOT_X = 40
LAST_DOT_X = 600

# Boundary offset for fine-tuning timeslot alignment
BOUNDARY_OFFSET = 2.75

# Boundary tolerance for filtering dots (HoughCircles imprecision)
BOUNDARY_TOLERANCE = 5

# Expected interval between data points (minutes)
EXPECTED_INTERVAL_MINUTES = 15

# Dots are detected in the cropped image; add this back to map to original space.
Y_MIN = 260


class ExtractionError(ValueError):
    """Raised for recoverable, user-facing extraction problems (e.g. bad image)."""


# Decompression-bomb guard. cv2.imdecode allocates the full bitmap before we ever
# check dimensions, so a tiny but highly-compressed file could blow up memory. A
# real Oura screenshot is 640x1136 (~0.73 MP); even high-res phone screenshots are
# only a few MP, so this leaves huge headroom while blocking multi-gigabyte bombs.
MAX_DECODE_PIXELS = 40_000_000  # ~40 MP -> ~120 MB decoded at 3 bytes/px


def _png_dimensions(data):
    """(width, height) from a PNG IHDR header, or None if not a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _jpeg_dimensions(data):
    """(width, height) from a JPEG SOF marker, or None if not a parseable JPEG."""
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:  # SOI
        return None
    i, n = 2, len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        # Standalone markers carry no length field.
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:
            i += 2
            continue
        if i + 4 > n:
            return None
        seg_len = (data[i + 2] << 8) | data[i + 3]
        # Start-of-Frame markers (excluding DHT/JPG/DAC) hold the dimensions.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > n:
                return None
            height = (data[i + 5] << 8) | data[i + 6]
            width = (data[i + 7] << 8) | data[i + 8]
            return width, height
        i += 2 + seg_len
    return None


def _guard_decompression_bomb(file_bytes):
    """Reject images whose header declares an absurd pixel count, before decode.

    Only PNG/JPEG headers are parsed (the formats this tool expects); unknown
    headers fall through to cv2.imdecode + validate_dimensions, and the upload
    size cap bounds the worst case for those.
    """
    dims = _png_dimensions(file_bytes) or _jpeg_dimensions(file_bytes)
    if dims is None:
        return
    width, height = dims
    if width * height > MAX_DECODE_PIXELS:
        raise ExtractionError(
            f"Image dimensions {width}x{height} are too large to process."
        )


def decode_image(file_bytes):
    """Decode uploaded bytes into a BGR image array, or raise ExtractionError."""
    _guard_decompression_bomb(file_bytes)
    arr = np.frombuffer(file_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ExtractionError("Could not decode image. Upload a PNG or JPEG screenshot.")
    return img


def validate_dimensions(img):
    """Ensure the screenshot matches the resolution the geometry assumes."""
    h, w = img.shape[:2]
    if (abs(w - EXPECTED_WIDTH) > DIMENSION_TOLERANCE
            or abs(h - EXPECTED_HEIGHT) > DIMENSION_TOLERANCE):
        raise ExtractionError(
            f"Unexpected image size {w}x{h}. This tool expects a "
            f"{EXPECTED_WIDTH}x{EXPECTED_HEIGHT} Oura 'Daytime Stress' screenshot "
            f"(iPhone SE/8 portrait). Crop/scaling will produce wrong results."
        )


def calculate_timestamp_from_timeslot(x_pos, first_dot_x, last_dot_x,
                                      first_time, last_time, offset=0):
    """Map an x-position to a timestamp by dividing the chart into equal slots."""
    total_minutes = (last_time - first_time).total_seconds() / 60
    total_timeslots = total_minutes / EXPECTED_INTERVAL_MINUTES

    x_range = last_dot_x - first_dot_x
    pixels_per_timeslot = x_range / total_timeslots

    pixels_from_start = x_pos - first_dot_x - offset
    timeslot_index = round(pixels_from_start / pixels_per_timeslot)

    return first_time + timedelta(minutes=timeslot_index * EXPECTED_INTERVAL_MINUTES)


def extract_from_array(screenshot, mask_path, reference_date, debug_ocr=False):
    """Extract stress points from a decoded BGR screenshot.

    Args:
        screenshot: BGR image array (already validated for size).
        mask_path: path to the bundled mask_scaled.png.
        reference_date: date the chart represents (from the user's form input).
        debug_ocr: forwarded to the OCR helper (writes debug crops to cwd).

    Returns:
        dict with:
          points:   list of {timestamp (ISO str), zone}
          gaps:     list of gap descriptors
          warnings: list of human-readable strings
          meta:     detection/timeslot diagnostics
          annotated: BGR image array with detected dots drawn (for optional preview)
    """
    warnings = []

    _, _, mask, blur = preprocess_array(screenshot, mask_path)

    first_time, last_time = extract_times_from_chart(
        screenshot, reference_date, debug=debug_ocr
    )

    circles = detect_dots(blur)
    for c in circles:
        c[1] += Y_MIN  # back to original-image coordinates

    filtered = [
        c for c in circles
        if (FIRST_DOT_X - BOUNDARY_TOLERANCE) <= c[0] <= (LAST_DOT_X + BOUNDARY_TOLERANCE)
    ]
    if not filtered:
        raise ExtractionError("No data points detected in the chart area.")

    points = []
    for (x, y, _r) in filtered:
        ts = calculate_timestamp_from_timeslot(
            x, FIRST_DOT_X, LAST_DOT_X, first_time, last_time, BOUNDARY_OFFSET
        )
        points.append({"timestamp": ts, "zone": zone_for_y(y), "x_pos": int(x), "y_pos": int(y)})

    points.sort(key=lambda p: p["timestamp"])

    # Duplicate-timestamp warning (two dots collapsed into one timeslot)
    seen = {}
    for p in points:
        seen[p["timestamp"]] = seen.get(p["timestamp"], 0) + 1
    dupes = sorted(ts for ts, n in seen.items() if n > 1)
    if dupes:
        warnings.append(
            f"{len(dupes)} duplicate timestamp(s) detected — two dots fell into the "
            f"same 15-min slot. Times may be slightly off."
        )

    # Build a small DataFrame-free gap check via the vendored helper.
    import pandas as pd
    df = pd.DataFrame([{"timestamp": p["timestamp"]} for p in points])
    gaps_raw = detect_gaps(df, EXPECTED_INTERVAL_MINUTES)
    gaps = [
        {
            "after": g["after"].isoformat(),
            "before": g["before"].isoformat(),
            "gap_minutes": g["gap_minutes"],
            "missing_points": g["missing_points"],
        }
        for g in gaps_raw
    ]

    if first_time < points[0]["timestamp"]:
        warnings.append(
            f"Possible missing data at start (chart begins {first_time:%H:%M}, "
            f"first dot at {points[0]['timestamp']:%H:%M})."
        )
    if last_time > points[-1]["timestamp"]:
        warnings.append(
            f"Possible missing data at end (last dot {points[-1]['timestamp']:%H:%M}, "
            f"chart ends {last_time:%H:%M})."
        )

    annotated = create_visualization(screenshot, filtered, df.assign(
        timestamp=[p["timestamp"] for p in points]))

    return {
        "points": [
            {"timestamp": p["timestamp"].isoformat(), "zone": p["zone"]}
            for p in points
        ],
        "gaps": gaps,
        "warnings": warnings,
        "meta": {
            "reference_date": reference_date.isoformat(),
            "first_time": first_time.isoformat(),
            "last_time": last_time.isoformat(),
            "detected_dots": len(circles),
            "used_dots": len(filtered),
        },
        "annotated": annotated,
    }
