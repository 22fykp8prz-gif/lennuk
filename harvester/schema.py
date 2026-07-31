"""Output schema for thesis records.

One row per thesis. Metadata is verbatim as supplied by the source:
no transliteration, no name normalisation, no translation at harvest time.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

# Column order for theses.parquet / theses.csv.
COLUMNS = [
    "id",
    "title_original",
    "title_en",
    "authors",
    "advisor",
    "year",
    "level",
    "level_raw",
    "institution",
    "faculty_dept",
    "language",
    "abstract",
    "keywords",
    "url_landing",
    "url_fulltext",
    "source",
    "harvested_at",
    "relevance_score",
    "national_flags",
    "domain_flags",
    "market_flags",
    "flags_version",
    "type_raw",
    "country",
]

LIST_COLUMNS = {"authors", "keywords", "national_flags", "domain_flags", "market_flags"}


def make_id(source: str, native_id: str) -> str:
    """Stable id: hash of source + the source's own identifier."""
    return hashlib.sha1(f"{source}::{native_id}".encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_record(source: str, native_id: str, **fields) -> dict:
    """Create a schema-complete record dict. Unknown fields are rejected."""
    rec = {c: None for c in COLUMNS}
    for c in LIST_COLUMNS:
        rec[c] = []
    rec["id"] = make_id(source, native_id)
    rec["source"] = source
    rec["harvested_at"] = now_iso()
    rec["level"] = "unknown"
    rec["relevance_score"] = 0
    for k, v in fields.items():
        if k not in COLUMNS:
            raise KeyError(f"unknown schema field: {k}")
        rec[k] = v
    return rec
