"""fetch-pdfs — download full texts for the filtered thesis subset.

Selection defaults to the reference-notes filter: level in (master,
doctoral) AND any market flag. Only records with a direct PDF URL are
fetched; records exposing just a landing page are logged as
`landing_only` (a next-pass/manual list), never scraped blindly.

Politeness and honesty rules match the harvester: ≤1 request/second per
host, robots.txt respected, a file already on disk is never re-fetched
(that's the resume), and every record's outcome lands in fetch_log.csv —
downloaded / already_present / landing_only / no_url / not_pdf / failed.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from .http import HarvestError, PoliteClient
from .schema import now_iso

FETCH_LOG_COLUMNS = ["timestamp", "id", "country", "institution", "title",
                     "url", "outcome", "path", "bytes"]


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "unknown").strip("_")[:60] or "unknown"


def _as_list(v) -> list:
    if v is None or isinstance(v, float):
        return []
    return list(v)


def select_records(df: pd.DataFrame, levels: list[str], selector: str) -> pd.DataFrame:
    """Filter to the download set. selector: market | domain | either."""
    picked = df[df["level"].isin(levels)].copy()
    market = picked["market_flags"].map(lambda v: len(_as_list(v)) > 0) \
        if "market_flags" in picked.columns else False
    domain = picked["domain_flags"].map(lambda v: len(_as_list(v)) > 0)
    if selector == "market":
        mask = market
    elif selector == "domain":
        mask = domain
    else:
        mask = market | domain
    return picked[mask]


def fetch_pdfs(
    out_dir: Path,
    dest_dir: Path,
    levels: list[str],
    selector: str = "market",
    dry_run: bool = False,
) -> int:
    df = pd.read_parquet(out_dir / "theses.parquet")
    subset = select_records(df, levels, selector)
    print(f"{len(subset)} of {len(df)} records match "
          f"(levels={','.join(levels)}, selector={selector})")

    client = PoliteClient(cache_dir=dest_dir / "_cache")  # cache unused; throttle/robots only
    rows = []
    counts: dict[str, int] = {}

    def log_row(rec, outcome, url="", path="", nbytes=None):
        counts[outcome] = counts.get(outcome, 0) + 1
        rows.append({
            "timestamp": now_iso(),
            "id": rec["id"],
            "country": rec.get("country") or "",
            "institution": rec.get("institution") or "",
            "title": (rec.get("title_original") or "")[:100],
            "url": url,
            "outcome": outcome,
            "path": path,
            "bytes": nbytes,
        })

    for rec in subset.to_dict("records"):
        url = rec.get("url_fulltext")
        url = url if isinstance(url, str) and url.startswith("http") else None
        landing = rec.get("url_landing")
        if url is None:
            if isinstance(landing, str) and landing.startswith("http"):
                log_row(rec, "landing_only", url=landing)
            else:
                log_row(rec, "no_url")
            continue

        target = (dest_dir / _slug(rec.get("country") or "xx")
                  / _slug(rec.get("institution") or "unknown") / f"{rec['id']}.pdf")
        if target.exists():
            log_row(rec, "already_present", url=url, path=str(target),
                    nbytes=target.stat().st_size)
            continue
        if dry_run:
            log_row(rec, "would_fetch", url=url)
            continue

        try:
            res = client.get(url, timeout=120, use_cache=False, skip_robots=False)
        except HarvestError as e:
            log_row(rec, f"failed ({e.kind})", url=url)
            continue
        if not res.body.startswith(b"%PDF"):
            # An HTML login/consent page is not the thesis; never save it as one.
            log_row(rec, "not_pdf", url=url)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(res.body)
        log_row(rec, "downloaded", url=url, path=str(target), nbytes=len(res.body))
        print(f"  {rec['id']} <- {url} ({len(res.body)//1024} KiB)")

    log_path = out_dir / "fetch_log.csv"
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FETCH_LOG_COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print("\nOutcomes: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"Log: {log_path}")
    if not dry_run:
        print(f"PDFs under: {dest_dir}")
    return 0
