"""Run ``python -m driftledger`` from a local checkout."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .core import InputError, compare, load_config, load_csv
from .report import render_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare feature distributions across two CSV snapshots")
    parser.add_argument("reference", help="baseline CSV")
    parser.add_argument("current", help="candidate CSV")
    parser.add_argument("--config", required=True, help="explicit feature types and alert thresholds, JSON")
    parser.add_argument("--out", required=True, help="new report directory; never overwritten")
    parser.add_argument("--fail-on-alert", action="store_true", help="exit 2 when any alert is found")
    parser.add_argument("--fail-on-review", action="store_true", help="also exit 2 when any item needs more data")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        report = compare(load_csv(args.reference), load_csv(args.current), config)
        report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
        json_text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        html_text = render_html(report)
        destination = Path(args.out)
        destination.mkdir(parents=False, exist_ok=False)
        (destination / "report.json").write_text(json_text, encoding="utf-8")
        (destination / "index.html").write_text(html_text, encoding="utf-8")
        print(f"{report['summary']['alerts']} alert(s), {report['summary']['reviews']} review item(s); {destination / 'index.html'}")
        return 2 if ((args.fail_on_alert and report["summary"]["alerts"])
                     or (args.fail_on_review and report["summary"]["reviews"])) else 0
    except (InputError, OSError) as error:
        print(f"DriftLedger: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
