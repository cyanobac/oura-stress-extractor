"""Dump the request log as CSV.

Usage:
    python -m app.logdump                 # CSV to stdout, newest first
    python -m app.logdump --out log.csv   # write to a file instead
    python -m app.logdump --limit 100     # only the 100 most recent rows
    REQUEST_LOG_DB=/data/requests.db python -m app.logdump

Reads the SQLite file directly (read-only) — no running server and no network
surface. This is the intended way to inspect logs on the public box; there is
deliberately no admin HTTP endpoint on a service that otherwise has no auth.
"""
import argparse
import csv
import os
import sqlite3
import sys

from . import requestlog

COLUMNS = ["id", "ts", "ip_hash", "processing_ms", "status", "success", "error"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Dump the request log as CSV.")
    parser.add_argument("--out", help="write CSV here instead of stdout")
    parser.add_argument("--limit", type=int, help="only the N most recent rows")
    args = parser.parse_args(argv)

    path = requestlog.db_path()
    # Read-only mode won't create a missing file, so an absent DB just means
    # nothing has been logged yet — say that plainly instead of leaking the raw
    # SQLite "unable to open database file" error.
    if not os.path.exists(path):
        print(
            f"No request log at {path} yet — no requests have been logged "
            f"(or REQUEST_LOG_DB points elsewhere / logging is disabled).",
            file=sys.stderr,
        )
        return 1
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.OperationalError as e:
        print(f"Could not open {path}: {e}", file=sys.stderr)
        return 1

    query = f"SELECT {', '.join(COLUMNS)} FROM request_log ORDER BY id DESC"
    if args.limit:
        query += f" LIMIT {int(args.limit)}"
    try:
        rows = conn.execute(query).fetchall()
    except sqlite3.OperationalError as e:
        print(f"No request_log table in {path}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        writer = csv.writer(out)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    finally:
        if args.out:
            out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
