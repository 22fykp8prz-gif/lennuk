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


def resolve_landing_pdf(html: str, base_url: str) -> tuple[str | None, str]:
    """Find the thesis PDF URL on a repository landing page.

    Order of trust: the citation_pdf_url meta tag (publisher-declared,
    machine-readable, exactly for this purpose), else a SINGLE unambiguous
    bitstream .pdf link. Multiple candidate links (Czech pages list referee
    reports as separate PDFs) are reported as ambiguous — never guessed.
    Returns (url or None, reason).
    """
    from urllib.parse import urljoin

    from lxml import html as lhtml

    try:
        doc = lhtml.fromstring(html)
    except Exception:
        return None, "unparseable_html"

    for meta in doc.xpath("//meta[@name='citation_pdf_url']"):
        content = (meta.get("content") or "").strip()
        if content:
            return urljoin(base_url, content), "citation_pdf_url"

    candidates = []
    for a in doc.xpath("//a[@href]"):
        href = a.get("href") or ""
        if ".pdf" in href.lower() and "bitstream" in href.lower():
            candidates.append(urljoin(base_url, href))
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) == 1:
        return candidates[0], "single_bitstream_link"
    if len(candidates) > 1:
        return None, f"ambiguous ({len(candidates)} pdf links)"
    return None, "no_pdf_link_found"


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

    def download(rec, url, target, outcome_label):
        try:
            res = client.get(url, timeout=120, use_cache=False, skip_robots=False)
        except HarvestError as e:
            log_row(rec, f"failed ({e.kind})", url=url)
            return
        if not res.body.startswith(b"%PDF"):
            # An HTML login/consent page is not the thesis; never save it as one.
            log_row(rec, "not_pdf", url=url)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(res.body)
        log_row(rec, outcome_label, url=url, path=str(target), nbytes=len(res.body))
        print(f"  {rec['id']} <- {url} ({len(res.body)//1024} KiB)")

    for rec in subset.to_dict("records"):
        url = rec.get("url_fulltext")
        url = url if isinstance(url, str) and url.startswith("http") else None
        landing = rec.get("url_landing")
        landing = landing if isinstance(landing, str) and landing.startswith("http") else None

        target = (dest_dir / _slug(rec.get("country") or "xx")
                  / _slug(rec.get("institution") or "unknown") / f"{rec['id']}.pdf")
        if target.exists():
            log_row(rec, "already_present", url=url or landing or "", path=str(target),
                    nbytes=target.stat().st_size)
            continue

        if url is not None:
            if dry_run:
                log_row(rec, "would_fetch", url=url)
            else:
                download(rec, url, target, "downloaded")
            continue

        if landing is None:
            log_row(rec, "no_url")
            continue

        # Landing page: resolve the declared PDF, never guess among many.
        if dry_run:
            log_row(rec, "would_resolve_landing", url=landing)
            continue
        try:
            page = client.get(landing, timeout=60, use_cache=False, skip_robots=False,
                              allow_error_status=True)
        except HarvestError as e:
            log_row(rec, f"landing_fetch_failed ({e.kind})", url=landing)
            continue
        if page.status != 200:
            log_row(rec, f"landing_fetch_failed (HTTP {page.status})", url=landing)
            continue
        pdf_url, reason = resolve_landing_pdf(page.text, landing)
        if pdf_url is None:
            log_row(rec, f"landing_{reason}", url=landing)
            continue
        download(rec, pdf_url, target, f"downloaded_via_{reason}")

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
