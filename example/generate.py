"""Generate synthetic support-routing snapshots; no customer data is used."""

from __future__ import annotations

import csv
from pathlib import Path
import random

ROOT = Path(__file__).parent
FIELDS = ["ticket_id", "region", "channel", "queue_minutes", "description_words", "priority"]


def build(seed: int, candidate: bool, count: int = 600) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows = []
    for index in range(count):
        region = rng.choices(["US", "EU"], weights=[65, 35])[0]
        channel = rng.choices(["email", "chat", "phone"],
                              weights=[25, 60, 15] if candidate else [50, 35, 15])[0]
        queue = max(1, round(rng.gauss(14, 4) + (11 if candidate and region == "EU" else 0), 1))
        words = max(1, round(rng.gauss(85, 20)))
        missing_words = rng.random() < (0.16 if candidate else 0.02)
        priority = rng.choices(["low", "medium", "high"], weights=[45, 40, 15])[0]
        rows.append({"ticket_id": f"{'new' if candidate else 'old'}-{index:04d}",
                     "region": region, "channel": channel, "queue_minutes": str(queue),
                     "description_words": "" if missing_words else str(words), "priority": priority})
    return rows


def main() -> None:
    for name, seed, candidate in (("reference.csv", 2026, False), ("current.csv", 2027, True)):
        with (ROOT / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(build(seed, candidate))


if __name__ == "__main__":
    main()
