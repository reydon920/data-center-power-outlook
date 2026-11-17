"""Validate snapshots, load DuckDB, and compute observed heat exposure."""

import csv
import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample"
HOUR = timedelta(hours=1)


def hours(start, end):
    """Yield an hourly grid with an exclusive end."""
    while start < end:
        yield start
        start += HOUR


def parse_hour(value):
    if len(value) != 10 or not value.isascii() or not value.isdigit():
        raise ValueError("Hourly timestamps must use YYYYMMDDHH")
    return datetime.strptime(value, "%Y%m%d%H")


def load_snapshot(folder=SAMPLE):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["units"] != "C" or manifest["time_standard"] != "UTC":
        raise ValueError("Snapshot must use Celsius and UTC")
    start, end = parse_hour(manifest["start"]), parse_hour(manifest["end_exclusive"])
    if start >= end:
        raise ValueError("Snapshot period must be positive")
    sites = manifest["sites"]
    ids = [site["id"] for site in sites]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Site identifiers must be unique and nonempty")
    path = folder / "temperatures.csv"
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["csv_sha256"]:
        raise ValueError("Snapshot checksum mismatch")
    rows = []
    seen = set()
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            site, stamp = row["site"], parse_hour(row["time"])
            if site not in ids or not start <= stamp < end:
                raise ValueError("Reading outside declared site or time range")
            if (site, stamp) in seen:
                raise ValueError("Duplicate site/hour")
            seen.add((site, stamp))
            temp = float(row["temperature_c"]) if row["temperature_c"] else None
            if temp is not None and (not math.isfinite(temp) or not -100 <= temp <= 70):
                raise ValueError("Invalid temperature; use blank for missing")
            rows.append((site, stamp, temp))
    # Connections never remain open during downloads or page generation.
    with duckdb.connect(":memory:") as connection:
        connection.execute("CREATE TABLE readings(site VARCHAR, stamp TIMESTAMP, temperature DOUBLE)")
        if rows:
            connection.executemany("INSERT INTO readings VALUES (?, ?, ?)", rows)
        ordered = connection.execute("SELECT * FROM readings ORDER BY site, stamp").fetchall()
    by_site = {site: {} for site in ids}
    for site, stamp, temp in ordered:
        by_site[site][stamp] = temp
    grid = list(hours(start, end))
    series = {site: [(stamp, by_site[site].get(stamp)) for stamp in grid] for site in ids}
    return manifest, series


def metrics(readings, threshold=30.0):
    """Strictly above threshold; no interpolation; gaps terminate a spell."""
    if not math.isfinite(threshold):
        raise ValueError("Threshold must be finite")
    expected = valid = hot = longest = run = 0
    degree_hours = 0.0
    previous = None
    for stamp, temp in readings:
        if stamp.minute or stamp.second or stamp.microsecond:
            raise ValueError("Readings must be aligned to whole hours")
        if previous is not None and stamp <= previous:
            raise ValueError("Readings must have unique, increasing timestamps")
        if previous is not None and stamp - previous != HOUR:
            run = 0
            expected += int((stamp - previous) / HOUR) - 1
        previous = stamp
        expected += 1
        if temp is None:
            run = 0
            continue
        if not math.isfinite(temp):
            raise ValueError("Temperature must be finite or None")
        valid += 1
        if temp > threshold:
            hot += 1
            degree_hours += temp - threshold
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return {"expected_hours": expected, "valid_hours": valid,
            "missing_hours": expected - valid,
            "coverage_pct": round(valid / expected * 100, 2) if expected else 0,
            "hot_hours": hot, "degree_hours_c_h": round(degree_hours, 2),
            "longest_spell_hours": longest}


def monthly_metrics(readings, threshold):
    groups = {}
    for stamp, temp in readings:
        groups.setdefault(stamp.strftime("%Y-%m"), []).append((stamp, temp))
    return {month: metrics(rows, threshold) for month, rows in groups.items()}


def compare(series, threshold):
    return {site: metrics(rows, threshold) for site, rows in series.items()}
