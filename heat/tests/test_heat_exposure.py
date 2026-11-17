import hashlib
import json
import shutil
import subprocess
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from heat_exposure.core import ROOT, SAMPLE, compare, load_snapshot, metrics, monthly_metrics
from heat_exposure.fetch import parse_response, source_url
from heat_exposure.site import build_site
from heat_exposure.showcase import render


@contextmanager
def test_directory():
    # Inherit directory permissions: private tempfile ACLs can exclude sandbox users.
    parent = (ROOT / "build").resolve()
    folder = parent / ("test-" + uuid.uuid4().hex)
    folder.mkdir(parents=True)
    try:
        yield folder
    finally:
        if folder.resolve().parent != parent:
            raise ValueError("Test cleanup escaped its build directory")
        shutil.rmtree(folder)


def readings(values, start=datetime(2025, 12, 31, 22)):
    return [(start + timedelta(hours=i), value) for i, value in enumerate(values)]


class MetricTests(unittest.TestCase):
    def test_hand_worked_example(self):
        result = metrics(readings([30, 32, 35, None, 34, 29, 31]), 30)
        self.assertEqual(result, {"expected_hours": 7, "valid_hours": 6, "missing_hours": 1,
                                  "coverage_pct": 85.71, "hot_hours": 4,
                                  "degree_hours_c_h": 12, "longest_spell_hours": 2})

    def test_missing_timestamp_breaks_spell(self):
        start = datetime(2025, 1, 1)
        rows = [(start, 35), (start + timedelta(hours=2), 36)]
        self.assertEqual(metrics(rows)["longest_spell_hours"], 1)
        self.assertEqual(metrics(rows)["missing_hours"], 1)
        self.assertEqual(metrics(rows)["coverage_pct"], 66.67)

    def test_year_boundary_continues_spell(self):
        rows = readings([32, 33, 34, 35])
        self.assertEqual(metrics(rows)["longest_spell_hours"], 4)
        self.assertEqual(list(monthly_metrics(rows, 30)), ["2025-12", "2026-01"])
        self.assertTrue(all(m["longest_spell_hours"] == 2 for m in monthly_metrics(rows, 30).values()))

    def test_empty_and_missing_are_not_hot(self):
        for values in ([], [None, None]):
            result = metrics(readings(values), -10)
            self.assertEqual(result["valid_hours"], 0)
            self.assertEqual(result["coverage_pct"], 0)
            self.assertEqual(result["hot_hours"], 0)
            self.assertEqual(result["longest_spell_hours"], 0)

    def test_threshold_updates_all_measures(self):
        rows = readings([30, 32, 35, 34])
        low, high = metrics(rows, 30), metrics(rows, 34)
        self.assertEqual((low["hot_hours"], low["degree_hours_c_h"], low["longest_spell_hours"]), (3, 11, 3))
        self.assertEqual((high["hot_hours"], high["degree_hours_c_h"], high["longest_spell_hours"]), (1, 1, 1))
        self.assertEqual(low["coverage_pct"], high["coverage_pct"])

    def test_invalid_inputs(self):
        for threshold in [float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                metrics([], threshold)
        with self.assertRaises(ValueError):
            metrics(readings([float("nan")]))
        with self.assertRaises(ValueError):
            metrics([(datetime(2025, 1, 1), 32)] * 2)


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Any accidental live networking in a test fails immediately.
        cls.network = patch("urllib.request.urlopen", side_effect=AssertionError("Tests must stay offline"))
        cls.network.start()
        cls.manifest, cls.series = load_snapshot()

    @classmethod
    def tearDownClass(cls):
        cls.network.stop()

    def test_recorded_nasa_snapshot(self):
        results = compare(self.series, 30)
        expected = {"ashburn": (457, 1043.61, 12), "phoenix": (2322, 13869.36, 44),
                    "sacramento": (835, 3518.83, 11)}
        for site, (hot, degrees, spell) in expected.items():
            row = results[site]
            self.assertEqual(row["valid_hours"], 8760)
            self.assertEqual(row["coverage_pct"], 100)
            self.assertEqual((row["hot_hours"], row["degree_hours_c_h"], row["longest_spell_hours"]), (hot, degrees, spell))
            monthly = monthly_metrics(self.series[site], 30)
            self.assertEqual(sum(m["hot_hours"] for m in monthly.values()), hot)
            self.assertAlmostEqual(sum(m["degree_hours_c_h"] for m in monthly.values()), degrees)

    def test_missing_grid_and_duplicate_validation(self):
        with test_directory() as directory:
            folder = Path(directory)
            manifest = dict(self.manifest)
            manifest.update(start="2025010100", end_exclusive="2025010103")
            content = b"site,time,temperature_c\nashburn,2025010100,35\nashburn,2025010102,36\n"
            (folder / "temperatures.csv").write_bytes(content)
            manifest["csv_sha256"] = hashlib.sha256(content).hexdigest()
            (folder / "manifest.json").write_text(json.dumps(manifest))
            _, series = load_snapshot(folder)
            result = metrics(series["ashburn"])
            self.assertEqual(result["missing_hours"], 1)
            self.assertEqual(result["longest_spell_hours"], 1)
            self.assertEqual(metrics(series["phoenix"])["missing_hours"], 3)
            content += b"ashburn,2025010102,36\n"
            (folder / "temperatures.csv").write_bytes(content)
            manifest["csv_sha256"] = hashlib.sha256(content).hexdigest()
            (folder / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_snapshot(folder)

    def test_checksum_detects_modified_data(self):
        with test_directory() as directory:
            folder = Path(directory)
            shutil.copy(SAMPLE / "manifest.json", folder)
            (folder / "temperatures.csv").write_text("changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_snapshot(folder)

    def test_units_and_utc_are_required(self):
        payload = {"header": {"time_standard": "UTC", "fill_value": -999},
                   "parameters": {"T2M": {"units": "C"}},
                   "properties": {"parameter": {"T2M": {"2025010100": -999, "2025010101": 0}}}}
        self.assertEqual(parse_response(payload), {"2025010100": None, "2025010101": 0})
        payload["header"]["time_standard"] = "LST"
        with self.assertRaises(ValueError):
            parse_response(payload)
        url = source_url(self.manifest["sites"][0], "20250101", "20251231")
        self.assertIn("time-standard=UTC", url)
        self.assertIn("parameters=T2M", url)

    def test_build_and_showcase(self):
        with test_directory() as directory:
            output = Path(directory)
            build_site(output, self.manifest, self.series, 30)
            page = (output / "index.html").read_text(encoding="utf-8")
            for marker in ["__DATA__", "__METRICS__", "__APP__"]:
                self.assertNotIn(marker, page)
            self.assertIn('"threshold":30', page)
            self.assertNotIn('<script src=', page)
            render(output, self.manifest, self.series, 30)
            for filename in ("comparison.png", "seasonal.png", "sensitivity.png"):
                with Image.open(output / filename) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertGreaterEqual(image.width, 1000)
                    self.assertGreater(len(image.getcolors(image.width * image.height)), 30)

    @unittest.skipUnless(shutil.which("node"), "Node is optional; needed only for browser-metric parity tests")
    def test_javascript_python_parity(self):
        script = """
const {calculate,monthly} = require('./heat_exposure/web/metrics.js');
const fs = require('fs');
const cases = JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(c=>({metrics:calculate(c.values,c.threshold),
  months:monthly(c.values,Date.UTC(2025,11,31,22),c.threshold)}))));
"""
        cases = [{"values": values, "threshold": threshold}
                 for values in ([30,32,35,None,34,29,31], [], [None,None], [30,30,30],
                                [0,-2,4,5,10,None,32,37,40])
                 for threshold in (-5, 0, 30, 34, 40)]
        cases += [{"values": [v for _,v in rows], "threshold": threshold}
                  for rows in self.series.values() for threshold in (20,25,30,35,40)]
        run = subprocess.run(["node", "-e", script], input=json.dumps(cases), text=True,
                             capture_output=True, cwd=ROOT, check=True)
        for case, actual in zip(cases, json.loads(run.stdout), strict=True):
            rows = readings(case["values"])
            self.assertEqual(actual["metrics"], metrics(rows, case["threshold"]))
            self.assertEqual(actual["months"], monthly_metrics(rows, case["threshold"]))

    @unittest.skipUnless(shutil.which("node"), "Node is optional for dashboard interaction tests")
    def test_dashboard_threshold_and_download(self):
        subprocess.run(["node", "tests/dashboard.cjs"], cwd=ROOT, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
