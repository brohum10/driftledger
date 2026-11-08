"""Reproduce end-to-end CSV parsing + comparison time on synthetic data."""

from __future__ import annotations

import argparse
import csv
import json
import platform
from pathlib import Path
import statistics
import tempfile
import time
import tracemalloc

from driftledger import compare, load_config, load_csv
from example.generate import FIELDS, build


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=25_000, help="rows per snapshot, 1–200000")
    parser.add_argument("--runs", type=int, default=3, help="number of complete timed runs, 1–10")
    parser.add_argument("--output", default="benchmark-results.json")
    args = parser.parse_args()
    if not 1 <= args.rows <= 200_000 or not 1 <= args.runs <= 10:
        parser.error("rows must be 1–200000 and runs 1–10")
    config = load_config("example/config.json")
    with tempfile.TemporaryDirectory() as folder:
        paths = [Path(folder) / "reference.csv", Path(folder) / "current.csv"]
        for path, seed, candidate in zip(paths, (2026, 2027), (False, True)):
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(build(seed, candidate, args.rows))
        durations, peaks, analysis_ids = [], [], []
        for _ in range(args.runs):
            tracemalloc.start()
            started = time.perf_counter()
            report = compare(load_csv(paths[0]), load_csv(paths[1]), config)
            durations.append(round((time.perf_counter() - started) * 1000, 2))
            peaks.append(round(tracemalloc.get_traced_memory()[1] / 1_000_000, 2))
            tracemalloc.stop()
            analysis_ids.append(report["analysis_id"])
        assert len(set(analysis_ids)) == 1
        result = {"rows_per_snapshot": args.rows, "runs": args.runs,
                  "timed_scope": "CSV parsing, validation, hashing, comparison; excludes data generation and HTML/JSON serialization",
                  "durations_ms": durations, "median_ms": round(statistics.median(durations), 2),
                  "peak_tracemalloc_mb": peaks, "alerts": report["summary"]["alerts"],
                  "analysis_id": report["analysis_id"], "python": platform.python_version(),
                  "platform": platform.platform()}
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
