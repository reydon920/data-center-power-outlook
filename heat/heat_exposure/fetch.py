"""Public NASA POWER download and reproducible normalized snapshot writer."""

import csv
import hashlib
import io
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .core import ROOT, hours

ENDPOINT = "https://power.larc.nasa.gov/api/temporal/hourly/point"


def source_url(site, start, end):
    return ENDPOINT + "?" + urlencode({
        "parameters": "T2M", "community": "SB", "latitude": site["latitude"],
        "longitude": site["longitude"], "start": start, "end": end,
        "format": "JSON", "time-standard": "UTC",
    })


def parse_response(payload):
    if payload.get("header", {}).get("time_standard") != "UTC":
        raise ValueError("NASA response must explicitly declare UTC")
    if payload.get("parameters", {}).get("T2M", {}).get("units") != "C":
        raise ValueError("NASA response must declare T2M in C")
    fill = payload["header"]["fill_value"]
    return {stamp: None if value == fill else value
            for stamp, value in payload["properties"]["parameter"]["T2M"].items()}


def download(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "DataCenterPowerOutlook/1.0"}), timeout=90) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def fetch_snapshot(output, start="20250101", end="20251231", sites_path=None, refresh=False):
    start_date = datetime.strptime(start, "%Y%m%d")
    end_date = datetime.strptime(end, "%Y%m%d") + timedelta(days=1)
    if start_date >= end_date or start_date.year != (end_date - timedelta(days=1)).year:
        raise ValueError("Fetch one calendar year or a shorter period per snapshot")
    sites = json.loads(Path(sites_path or ROOT / "data/sites.json").read_text(encoding="utf-8"))
    ids = [site["id"] for site in sites]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Supply unique site ids")
    for site in sites:
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", site["id"]):
            raise ValueError("Site ids must be lowercase slugs")
        if not -90 <= site["latitude"] <= 90 or not -180 <= site["longitude"] <= 180:
            raise ValueError("Coordinates outside geographic bounds")
    cache = ROOT / "data/raw"
    cache.mkdir(parents=True, exist_ok=True)
    rows, sources = [], []
    for site in sites:
        url = source_url(site, start, end)
        key = hashlib.sha256(url.encode()).hexdigest()
        cached = cache / (key + ".json")
        if cached.exists() and not refresh:
            record = json.loads(cached.read_text(encoding="utf-8"))
        else:
            raw = download(url)
            payload = json.loads(raw)
            parse_response(payload)
            record = {"url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                      "response_sha256": hashlib.sha256(raw).hexdigest(), "payload": payload}
            cached.write_text(json.dumps(record), encoding="utf-8")
        values = parse_response(record["payload"])
        for stamp in hours(start_date, end_date):
            key = stamp.strftime("%Y%m%d%H")
            rows.append((site["id"], key, values.get(key)))
        sources.append({k: v for k, v in record.items() if k != "payload"} | {"site": site["id"]})
        print(f"Fetched {site['name']}: {len(values):,} source hours", flush=True)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["site", "time", "temperature_c"])
    writer.writerows(rows)
    content = buffer.getvalue().encode("utf-8")
    manifest = {"source": "NASA POWER hourly T2M", "units": "C", "time_standard": "UTC",
                "start": start_date.strftime("%Y%m%d%H"), "end_exclusive": end_date.strftime("%Y%m%d%H"),
                "sites": sites, "sources": sources, "csv_sha256": hashlib.sha256(content).hexdigest()}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "temperatures.csv").write_bytes(content)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
