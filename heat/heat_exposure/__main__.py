"""Command line interface. All commands except fetch operate offline."""

import argparse
import json
import sys
from pathlib import Path
from urllib.error import URLError

from .core import SAMPLE, compare, load_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description="Heat Exposure | Outdoor heat screening")
    parser.add_argument("--data", type=Path, default=SAMPLE, help="Snapshot directory")
    parser.add_argument("--threshold", type=float, default=30.0, help="Screening threshold in C")
    parser.add_argument("--showcase", type=Path, metavar="DIRECTORY", help="Render offline PNG reports")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("report", help="Print heat metrics as JSON")
    build = sub.add_parser("build", help="Build a self-contained interactive HTML dashboard")
    build.add_argument("--output", type=Path, default=Path("docs/site"))
    fetch = sub.add_parser("fetch", help="Download NASA POWER data (network required)")
    fetch.add_argument("--start", default="20250101")
    fetch.add_argument("--end", default="20251231")
    fetch.add_argument("--sites", type=Path)
    fetch.add_argument("--output", type=Path, default=Path("data/sample"))
    fetch.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            from .fetch import fetch_snapshot
            fetch_snapshot(args.output, args.start, args.end, args.sites, args.refresh)
            return 0
        manifest, series = load_snapshot(args.data)
        result = compare(series, args.threshold)
        if args.showcase:
            from .showcase import render
            render(args.showcase, manifest, series, args.threshold)
            print(f"Wrote PNG reports to {args.showcase}")
        elif args.command == "build":
            from .site import build_site
            build_site(args.output, manifest, series, args.threshold)
            print(f"Open {args.output / 'index.html'}")
        else:
            print(json.dumps({"threshold_c": args.threshold, "time_standard": "UTC", "sites": result}, indent=2))
        return 0
    except (ValueError, KeyError, OSError, URLError) as error:
        print(f"Heat exposure: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
