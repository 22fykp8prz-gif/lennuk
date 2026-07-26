"""Harvest log: one row per source attempted.

A source that failed must appear here as a failure — never as zero results
silently.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .schema import now_iso

LOG_COLUMNS = [
    "timestamp",
    "source",
    "institution",
    "endpoint",
    "records_returned",
    "http_status",
    "outcome",  # ok | ok_empty | failed | skipped
    "error",
    "note",
]


class HarvestLog:
    def __init__(self):
        self.rows: list[dict] = []

    def add(
        self,
        source: str,
        endpoint: str,
        outcome: str,
        institution: str = "",
        records_returned: int | None = None,
        http_status: int | None = None,
        error: str = "",
        note: str = "",
    ) -> None:
        self.rows.append(
            {
                "timestamp": now_iso(),
                "source": source,
                "institution": institution,
                "endpoint": endpoint,
                "records_returned": records_returned,
                "http_status": http_status,
                "outcome": outcome,
                "error": error,
                "note": note,
            }
        )

    def write_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
            w.writeheader()
            w.writerows(self.rows)
