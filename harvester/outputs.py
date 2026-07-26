"""Dataset assembly: cross-source dedup, parquet/csv output."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .schema import COLUMNS, LIST_COLUMNS

# When the same thesis arrives from several sources, prefer richer sources.
_SOURCE_PRIORITY = {"oai-pmh": 0, "yok": 1, "openaire": 2}


def _priority(source: str) -> int:
    for prefix, p in _SOURCE_PRIORITY.items():
        if source.startswith(prefix):
            return p
    return 9


def dedupe(records: list[dict]) -> list[dict]:
    """Drop exact id duplicates, then collapse cross-source duplicates on
    (casefolded title, year, institution), keeping the richest source."""
    by_id: dict[str, dict] = {}
    for r in records:
        by_id.setdefault(r["id"], r)

    by_key: dict[tuple, dict] = {}
    keyless: list[dict] = []
    for r in by_id.values():
        title = (r.get("title_original") or "").casefold().strip()
        if not title:
            keyless.append(r)
            continue
        key = (title, r.get("year"), r.get("institution"))
        cur = by_key.get(key)
        if cur is None:
            by_key[key] = r
        elif _priority(r["source"]) < _priority(cur["source"]):
            by_key[key] = _merge(r, cur)
        else:
            by_key[key] = _merge(cur, r)
    return list(by_key.values()) + keyless


def _merge(primary: dict, secondary: dict) -> dict:
    """Fill primary's empty fields from secondary — never overwrite."""
    out = dict(primary)
    for k in COLUMNS:
        if (out.get(k) in (None, "", [])) and secondary.get(k) not in (None, "", []):
            out[k] = secondary[k]
    return out


def to_dataframe(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records, columns=COLUMNS)
    if df.empty:
        df = pd.DataFrame(columns=COLUMNS)
    return df


def write_outputs(records: list[dict], out_dir: Path) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = to_dataframe(records)
    df.to_parquet(out_dir / "theses.parquet", index=False)
    csv_df = df.copy()
    for c in LIST_COLUMNS:
        csv_df[c] = csv_df[c].map(lambda v: "|".join(v) if isinstance(v, list) else v)
    csv_df.to_csv(out_dir / "theses.csv", index=False)
    return df
