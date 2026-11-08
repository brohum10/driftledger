from __future__ import annotations

import csv
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from driftledger import InputError, compare, jensen_shannon, load_config, load_csv, total_variation
from driftledger.core import Dataset
from driftledger.report import render_html
from driftledger.__main__ import main


def dataset(columns: tuple[str, ...], rows: list[dict[str, str]]) -> Dataset:
    return Dataset("fixture", "a" * 64, columns, tuple(rows))


CONFIG = {"features": {"x": "numeric", "kind": "categorical"}, "segment_by": "group",
          "thresholds": {"numeric_tv": 0.2, "categorical_js": 0.05, "missing_delta": 0.2},
          "min_rows": 2, "min_segment_rows": 2}


class MetricTests(unittest.TestCase):
    def test_numeric_tv_uses_reference_bins_and_handles_constant_reference(self):
        self.assertEqual(total_variation([0, 0, 0], [1, 1, 1])[0], 1)
        self.assertEqual(total_variation([0, 0, 0], [0, 0, 0])[0], 0)
        self.assertEqual(total_variation([0, 0, 0], [-1, -1, -1])[0], 1)
        self.assertEqual(total_variation([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])[0], 0)

    def test_categorical_js_is_symmetric_and_bounded(self):
        self.assertAlmostEqual(jensen_shannon(["a"] * 10, ["b"] * 10)[0], 1)
        self.assertEqual(jensen_shannon(["a", "b"], ["a", "b"])[0], 0)
        left = jensen_shannon(["a", "a", "b"], ["b", "b", "c"])[0]
        right = jensen_shannon(["b", "b", "c"], ["a", "a", "b"])[0]
        self.assertAlmostEqual(left, right)
        self.assertTrue(0 < left < 1)

    def test_cohort_shift_can_be_hidden_globally(self):
        before = dataset(("group", "x", "kind"),
                         [{"group": g, "x": str(value), "kind": "stable"}
                          for g, value in (("EU", 0), ("US", 10)) for _ in range(30)])
        after = dataset(("group", "x", "kind"),
                        [{"group": g, "x": str(value), "kind": "stable"}
                         for g, value in (("EU", 10), ("US", 0)) for _ in range(30)])
        report = compare(before, after, CONFIG)
        self.assertEqual(report["global"][0]["score"], 0)
        self.assertEqual([group["features"][0]["score"] for group in report["segments"]], [1, 1])
        self.assertEqual(report["summary"]["score_alerts"], 2)

    def test_missingness_and_sparse_cohorts_are_explicit(self):
        before = dataset(("group", "x", "kind"), [{"group": "A", "x": "1", "kind": "a"}] * 10)
        after = dataset(("group", "x", "kind"), [{"group": "A", "x": "", "kind": "a"}] * 4
                        + [{"group": "B", "x": "1", "kind": "a"}] * 6)
        report = compare(before, after, CONFIG)
        self.assertIn("missing_delta", report["global"][0]["alerts"])
        self.assertEqual(report["segments"][1]["status"], "insufficient_rows")
        self.assertGreaterEqual(report["summary"]["cohort_alerts"], 1)
        self.assertGreaterEqual(report["summary"]["reviews"], 1)

    def test_schema_changes_count_each_column_once(self):
        before = dataset(("group", "x", "kind"), [{"group": "A", "x": "1", "kind": "a"}] * 3)
        after = dataset(("group", "kind", "extra"), [{"group": "A", "kind": "a", "extra": "v"}] * 3)
        report = compare(before, after, CONFIG)
        self.assertEqual(report["schema"]["missing_configured_features"], ["x"])
        self.assertEqual(report["summary"]["schema_alerts"], 2)

    def test_invalid_number_rejected(self):
        before = dataset(("group", "x", "kind"), [{"group": "A", "x": "nan", "kind": "a"}] * 3)
        with self.assertRaisesRegex(InputError, "non-finite"):
            compare(before, before, CONFIG)

    def test_missing_segment_labels_are_measured_separately(self):
        before = dataset(("group", "x", "kind"), [{"group": "A", "x": "1", "kind": "a"}] * 10)
        after = dataset(("group", "x", "kind"), [{"group": "", "x": "1", "kind": "a"}] * 4
                        + [{"group": "A", "x": "1", "kind": "a"}] * 6)
        report = compare(before, after, CONFIG)
        self.assertEqual(report["segment_missing"]["delta"], 0.4)
        self.assertTrue(report["segment_missing"]["alert"])
        self.assertEqual(report["summary"]["cohort_alerts"], 1)

    def test_extreme_finite_median_stays_finite_in_json(self):
        rows = [{"group": "A", "x": "1e308", "kind": "a"}] * 2
        report = compare(dataset(("group", "x", "kind"), rows), dataset(("group", "x", "kind"), rows), CONFIG)
        self.assertEqual(report["global"][0]["median_before"], 1e308)
        json.dumps(report, allow_nan=False)


class InputAndReportTests(unittest.TestCase):
    def test_csv_loader_rejects_duplicate_and_ragged_headers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.csv"
            path.write_text("x,x\n1,2\n", encoding="utf-8")
            with self.assertRaisesRegex(InputError, "duplicate"):
                load_csv(path)
            path.write_text("x,y\n1\n", encoding="utf-8")
            with self.assertRaisesRegex(InputError, "ragged"):
                load_csv(path)

    def test_config_rejects_unknown_keys_and_invalid_thresholds(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps({"features": {"x": "numeric"}, "typo": True}))
            with self.assertRaisesRegex(InputError, "Unknown"):
                load_config(path)
            path.write_text(json.dumps({"features": {"x": "numeric"}, "thresholds": {"numeric_tv": 0}}))
            with self.assertRaisesRegex(InputError, "numeric_tv"):
                load_config(path)

    def test_html_escapes_user_controlled_column_and_cohort_names(self):
        config = {**CONFIG, "features": {"<img src=x onerror=alert(1)>": "categorical"},
                  "segment_by": None}
        before = dataset(("<img src=x onerror=alert(1)>",), [{"<img src=x onerror=alert(1)>": "a"}] * 3)
        report = compare(before, before, config)
        html = render_html(report)
        self.assertIn("&lt;img", html)
        self.assertNotIn("<img src=x", html)

    def test_cli_writes_new_directory_and_gate_returns_two(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, values in (("before.csv", ["a"] * 4), ("after.csv", ["b"] * 4)):
                with (root / name).open("w", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["kind"])
                    writer.writerows([value] for value in values)
            (root / "config.json").write_text(json.dumps({"features": {"kind": "categorical"}, "min_rows": 2}))
            args = [str(root / "before.csv"), str(root / "after.csv"), "--config", str(root / "config.json"),
                    "--out", str(root / "report"), "--fail-on-alert"]
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(args), 2)
            self.assertTrue((root / "report" / "index.html").exists())
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(main(args), 1)


if __name__ == "__main__":
    unittest.main()
