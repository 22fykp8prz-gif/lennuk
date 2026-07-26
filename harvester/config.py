"""Configuration: institutions.csv loading and global constants."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Harvest window (defence/publication year, inclusive).
YEAR_FROM = 2021
YEAR_TO = 2026

# Politeness.
MIN_INTERVAL_PER_HOST = 1.0  # seconds; never more than 1 req/s per host
BACKOFF_SCHEDULE = [2, 4, 8, 16]  # seconds, on 429/5xx

CONTACT = os.environ.get("HARVESTER_CONTACT", "unset-contact@example.invalid")
USER_AGENT = (
    "lennuk-thesis-harvester/0.1 "
    f"(academic metadata harvest, theses 2021-2026; contact: {CONTACT})"
)

OPENAIRE_BASE = "https://api.openaire.eu/graph/v2/researchProducts"


@dataclass
class Institution:
    country: str
    institution_id: str
    institution_en: str
    institution_native: str
    tier: str
    repo_base_url: str
    repo_software_hint: str
    openaire_org_name: str
    national_system: str
    yok_university_name: str
    pilot: bool
    notes: str


def load_institutions(path: Path | None = None) -> list[Institution]:
    path = path or PROJECT_ROOT / "institutions.csv"
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(
                Institution(
                    country=row["country"].strip(),
                    institution_id=row["institution_id"].strip(),
                    institution_en=row["institution_en"].strip(),
                    institution_native=row["institution_native"].strip(),
                    tier=row["tier"].strip(),
                    repo_base_url=row["repo_base_url"].strip(),
                    repo_software_hint=row["repo_software_hint"].strip(),
                    openaire_org_name=row["openaire_org_name"].strip(),
                    national_system=row["national_system"].strip(),
                    yok_university_name=row["yok_university_name"].strip(),
                    pilot=row["pilot"].strip() == "1",
                    notes=row["notes"].strip(),
                )
            )
    return out
