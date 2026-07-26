"""gaps.csv — institutions with no machine-readable route, and why.

This file is a deliverable in its own right: it says where to send an email
instead of a harvester. Coverage is never fabricated to avoid a gap line.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .config import Institution
from .log import HarvestLog

GAP_COLUMNS = ["country", "institution", "what_was_tried", "what_exists", "suggested_route"]


def write_gaps(
    institutions: list[Institution],
    log: HarvestLog,
    harvested_institutions: set[str],
    out_path: Path,
) -> None:
    rows = []
    failures_by_inst: dict[str, list[str]] = {}
    for r in log.rows:
        if r["outcome"] in ("failed", "skipped") and r["institution"]:
            failures_by_inst.setdefault(r["institution"], []).append(
                f"{r['source']} {r['endpoint']}: {r['error'] or r['note']}"
            )

    for inst in institutions:
        if inst.institution_en in harvested_institutions:
            continue
        tried = "; ".join(failures_by_inst.get(inst.institution_en, [])) or "nothing attempted yet"
        exists = inst.notes or "unknown — needs manual survey"
        if inst.national_system == "yok":
            route = "YÖK Ulusal Tez Merkezi browser module (tier 3)"
        elif inst.national_system:
            route = f"national system: {inst.national_system} (tier 3)"
        elif not inst.repo_base_url:
            route = "no known repository — contact university library / faculty directly"
        else:
            route = f"repository {inst.repo_base_url} — verify endpoint manually"
        rows.append(
            {
                "country": inst.country,
                "institution": inst.institution_en,
                "what_was_tried": tried,
                "what_exists": exists,
                "suggested_route": route,
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=GAP_COLUMNS)
        w.writeheader()
        w.writerows(rows)
