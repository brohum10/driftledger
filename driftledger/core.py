"""Deterministic, dependency-free feature-distribution comparisons."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

MAX_BYTES = 25_000_000
MAX_ROWS = 200_000
MAX_SEGMENTS = 25
DEFAULT_THRESHOLDS = {"numeric_tv": 0.18, "categorical_js": 0.08, "missing_delta": 0.10}


class InputError(ValueError):
    """The caller supplied data or configuration outside the documented contract."""


@dataclass(frozen=True)
class Dataset:
    path: str
    sha256: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, str], ...]


def load_csv(path: str | Path) -> Dataset:
    file = Path(path)
    if not file.is_file() or file.stat().st_size > MAX_BYTES:
        raise InputError(f"{file}: file missing or larger than {MAX_BYTES:,} bytes")
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    with file.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        columns = reader.fieldnames
        if not columns or any(not name or not name.strip() for name in columns):
            raise InputError(f"{file}: CSV needs nonempty column names")
        if len(columns) != len(set(columns)):
            raise InputError(f"{file}: duplicate column names")
        rows = []
        try:
            for row in reader:
                if len(rows) >= MAX_ROWS:
                    raise InputError(f"{file}: more than {MAX_ROWS:,} rows")
                if None in row or any(value is None for value in row.values()):
                    raise InputError(f"{file}: ragged CSV row {reader.line_num}")
                rows.append({name: value.strip() for name, value in row.items()})
        except csv.Error as error:
            raise InputError(f"{file}: malformed CSV: {error}") from error
    if not rows:
        raise InputError(f"{file}: CSV has no data rows")
    return Dataset(str(file), digest, tuple(columns), tuple(rows))


def load_config(path: str | Path) -> dict:
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"Cannot read config: {error}") from error
    if not isinstance(config, dict):
        raise InputError("Config must be a JSON object")
    unknown = set(config) - {"features", "segment_by", "thresholds", "min_rows", "min_segment_rows"}
    if unknown:
        raise InputError(f"Unknown config keys: {', '.join(sorted(unknown))}")
    features = config.get("features")
    if not isinstance(features, dict) or not features:
        raise InputError("features must be a nonempty object")
    if any(not isinstance(name, str) or not name or kind not in {"numeric", "categorical"}
           for name, kind in features.items()):
        raise InputError("Every feature needs a name and type numeric or categorical")
    segment_by = config.get("segment_by")
    if segment_by is not None and (not isinstance(segment_by, str) or not segment_by or segment_by in features):
        raise InputError("segment_by must name a separate categorical column")
    thresholds = dict(DEFAULT_THRESHOLDS)
    overrides = config.get("thresholds", {})
    if not isinstance(overrides, dict) or set(overrides) - set(thresholds):
        raise InputError("thresholds may only override numeric_tv, categorical_js, missing_delta")
    thresholds.update(overrides)
    for name, value in thresholds.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 1:
            raise InputError(f"{name} must be a finite number in (0, 1]")
    min_rows = config.get("min_rows", 20)
    min_segment_rows = config.get("min_segment_rows", 30)
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 2 for n in (min_rows, min_segment_rows)):
        raise InputError("min_rows and min_segment_rows must be integers >= 2")
    return {"features": features, "segment_by": segment_by, "thresholds": thresholds,
            "min_rows": min_rows, "min_segment_rows": min_segment_rows}


def _values(rows: tuple[dict[str, str], ...], name: str, kind: str) -> tuple[list, int]:
    values = []
    missing = 0
    for index, row in enumerate(rows, start=2):
        raw = row[name]
        if not raw:
            missing += 1
            continue
        if kind == "numeric":
            try:
                value = float(raw)
            except ValueError as error:
                raise InputError(f"{name}: invalid number at data row {index}") from error
            if not math.isfinite(value):
                raise InputError(f"{name}: non-finite number at data row {index}")
            values.append(value)
        else:
            values.append(raw)
    return values, missing


def _reference_edges(values: list[float]) -> list[float]:
    ordered = sorted(values)
    n = len(ordered)
    return sorted({ordered[0], ordered[-1], *(ordered[min(n - 1, math.ceil(n * q / 5) - 1)] for q in range(1, 5))})


def _numeric_histogram(values: list[float], edges: list[float]) -> list[int]:
    counts = [0] * (len(edges) + 2)
    for value in values:
        if value < edges[0]:
            bucket = 0
        elif value > edges[-1]:
            bucket = len(edges) + 1
        else:
            bucket = bisect_right(edges, value)
        counts[bucket] += 1
    return counts


def total_variation(reference: list[float], current: list[float]) -> tuple[float, int]:
    """TV distance between histograms using reference-only quintile cut points."""
    if not reference or not current:
        raise ValueError("Both nonmissing samples are required")
    edges = _reference_edges(reference)
    left = _numeric_histogram(reference, edges)
    right = _numeric_histogram(current, edges)
    score = 0.5 * sum(abs(a / len(reference) - b / len(current)) for a, b in zip(left, right))
    return min(1.0, score), len(edges) + 2


def jensen_shannon(reference: list[str], current: list[str]) -> tuple[float, int]:
    """Jensen-Shannon divergence in bits, bounded between zero and one."""
    if not reference or not current:
        raise ValueError("Both nonmissing samples are required")
    left, right = Counter(reference), Counter(current)
    left_total, right_total = len(reference), len(current)
    def kl_half(a: Counter, b: Counter) -> float:
        result = 0.0
        a_total, b_total = (left_total, right_total) if a is left else (right_total, left_total)
        for category, count in a.items():
            p = count / a_total
            q = b[category] / b_total
            result += 0.5 * p * math.log2(p / (0.5 * (p + q)))
        return result
    return min(1.0, max(0.0, kl_half(left, right) + kl_half(right, left))), len(set(left) | set(right))


def _round(value: float) -> float:
    return round(value, 6)


def _safe_median(values: list[float]) -> float:
    ordered = sorted(values)
    center = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[center]
    return ordered[center - 1] / 2 + ordered[center] / 2


def _feature(name: str, kind: str, before: tuple[dict[str, str], ...],
             after: tuple[dict[str, str], ...], config: dict, min_rows: int) -> dict:
    left, missing_left = _values(before, name, kind)
    right, missing_right = _values(after, name, kind)
    missing_before = missing_left / len(before)
    missing_after = missing_right / len(after)
    missing_delta = _round(abs(missing_after - missing_before))
    alerts = []
    if missing_delta >= config["thresholds"]["missing_delta"]:
        alerts.append("missing_delta")
    item = {"feature": name, "kind": kind, "before_count": len(left), "after_count": len(right),
            "missing_before": _round(missing_before), "missing_after": _round(missing_after),
            "missing_delta": _round(missing_delta), "alerts": alerts}
    if len(left) < min_rows or len(right) < min_rows:
        item.update({"score": None, "score_name": "numeric_tv" if kind == "numeric" else "categorical_js",
                     "status": "insufficient_nonmissing_rows", "min_required": min_rows})
        return item
    if kind == "numeric":
        score, buckets = total_variation(left, right)
        item.update({"score_name": "numeric_tv", "score": _round(score), "buckets": buckets,
                     "median_before": _round(_safe_median(left)), "median_after": _round(_safe_median(right))})
    else:
        score, categories = jensen_shannon(left, right)
        item.update({"score_name": "categorical_js", "score": _round(score),
                     "categories": categories, "new_categories": len(set(right) - set(left))})
    if item["score"] >= config["thresholds"][item["score_name"]]:
        alerts.append(item["score_name"])
    item["status"] = "alert" if alerts else "pass"
    return item


def compare(before: Dataset, after: Dataset, config: dict) -> dict:
    """Compare explicit features globally and for each sufficiently large cohort."""
    baseline_columns, current_columns = set(before.columns), set(after.columns)
    schema = {"removed_columns": sorted(baseline_columns - current_columns),
              "added_columns": sorted(current_columns - baseline_columns)}
    features = config["features"]
    missing_features = sorted(set(features) - (baseline_columns & current_columns))
    segment_by = config["segment_by"]
    if segment_by and segment_by not in baseline_columns & current_columns:
        schema["segment_column_missing"] = segment_by
    def analyze(left_rows, right_rows, minimum):
        return [_feature(name, kind, left_rows, right_rows, config, minimum)
                for name, kind in features.items() if name not in missing_features]
    global_results = analyze(before.rows, after.rows, config["min_rows"])
    segments = []
    segment_missing = None
    if segment_by and not schema.get("segment_column_missing"):
        missing_before = sum(not row[segment_by] for row in before.rows) / len(before.rows)
        missing_after = sum(not row[segment_by] for row in after.rows) / len(after.rows)
        missing_delta = _round(abs(missing_after - missing_before))
        segment_missing = {"before": _round(missing_before), "after": _round(missing_after),
                           "delta": missing_delta,
                           "alert": missing_delta >= config["thresholds"]["missing_delta"]}
        left_groups = Counter(row[segment_by] for row in before.rows if row[segment_by])
        right_groups = Counter(row[segment_by] for row in after.rows if row[segment_by])
        names = sorted(set(left_groups) | set(right_groups))
        if len(names) > MAX_SEGMENTS:
            raise InputError(f"segment_by has more than {MAX_SEGMENTS} values")
        for name in names:
            left_rows = tuple(row for row in before.rows if row[segment_by] == name)
            right_rows = tuple(row for row in after.rows if row[segment_by] == name)
            available = min(len(left_rows), len(right_rows)) >= config["min_segment_rows"]
            segments.append({"name": name, "before_count": len(left_rows), "after_count": len(right_rows),
                             "status": "compared" if available else "insufficient_rows",
                             "features": analyze(left_rows, right_rows, config["min_segment_rows"]) if available else []})
    all_results = global_results + [feature for segment in segments for feature in segment["features"]]
    score_alerts = sum(len(item["alerts"]) for item in all_results)
    changed_names = set(schema["removed_columns"]) | set(schema["added_columns"]) | set(missing_features)
    if schema.get("segment_column_missing"):
        changed_names.add(segment_by)
    schema_alerts = len(changed_names)
    # New or vanished cohorts are explicit coverage alerts, not misleading distribution scores.
    cohort_alerts = sum(1 for segment in segments if not segment["before_count"] or not segment["after_count"])
    cohort_alerts += int(bool(segment_missing and segment_missing["alert"]))
    reviews = sum(item["status"] == "insufficient_nonmissing_rows" for item in all_results)
    reviews += sum(segment["status"] == "insufficient_rows" and segment["before_count"] and segment["after_count"] for segment in segments)
    alert_count = score_alerts + schema_alerts + cohort_alerts
    analysis_id = hashlib.sha256((before.sha256 + after.sha256 + json.dumps(config, sort_keys=True)).encode()).hexdigest()
    return {"schema_version": 1, "analysis_id": analysis_id,
            "reference": {"sha256": before.sha256, "rows": len(before.rows)},
            "current": {"sha256": after.sha256, "rows": len(after.rows)}, "config": config,
            "schema": {**schema, "missing_configured_features": missing_features},
            "global": global_results, "segments": segments, "segment_missing": segment_missing,
            "summary": {"alerts": alert_count, "score_alerts": score_alerts,
                        "schema_alerts": schema_alerts, "cohort_alerts": cohort_alerts,
                        "reviews": reviews, "passed": alert_count == 0}}
