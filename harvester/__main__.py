"""CLI entrypoint.

    python -m harvester run --phase 0 [--out output/phase0] [--data data]

Phase 0: the three pilot institutions (pilot=1 in institutions.csv),
full pipeline end to end, then stop.
Phase 1: all tier-A institutions, tiers 1+2.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import csv

from .config import PROJECT_ROOT, load_institutions
from .flags import FLAG_NAMES, FlagMatcher
from .gaps import write_gaps
from .http import PoliteClient
from .log import HarvestLog
from .outputs import dedupe, drop_nonthesis, drop_reviews, write_outputs
from .report import write_coverage_report, write_sample_rows
from . import tier1_openaire, tier2_oaipmh, tier3_yok


def run(phase: int, out_dir: Path, data_dir: Path, offline: bool = False) -> int:
    institutions = load_institutions()
    if phase == 0:
        targets = [i for i in institutions if i.pilot]
    elif phase == 1:
        targets = [i for i in institutions if i.tier == "A" and i.national_system != "yok"]
    else:
        raise SystemExit(f"phase {phase} not implemented yet (phases 2-3 follow the pilot review)")

    log = HarvestLog()
    client = PoliteClient(cache_dir=data_dir / "raw", offline=offline)
    records: list[dict] = []
    harvested: set[str] = set()

    for inst in targets:
        print(f"=== {inst.country} / {inst.institution_en} ===")
        n_before = len(records)

        # Each tier is fenced per institution: one unexpected failure must
        # be a logged hole, never the end of a multi-hour run.
        def _fenced(tier_name, fn):
            try:
                return fn()
            except Exception as e:
                log.add(tier_name, inst.repo_base_url or tier_name, "failed",
                        institution=inst.institution_en,
                        error=f"unexpected {type(e).__name__}: {e}")
                print(f"    !! {tier_name} failed unexpectedly: {e}")
                return []

        # Tier 1 — OpenAIRE first pass (not for YÖK-only institutions,
        # Turkish theses are not aggregated there in useful numbers).
        if inst.national_system != "yok":
            records += _fenced("openaire", lambda: tier1_openaire.harvest_institution(inst, client, log))

        # Tier 2 — direct OAI-PMH where a repository is configured.
        if inst.repo_base_url:
            records += _fenced("oai-pmh", lambda: tier2_oaipmh.harvest_institution(
                inst, client, log, meta_dir=data_dir / "meta"))

        # Tier 3 — YÖK browser module, its own log file as well.
        if inst.national_system == "yok":
            records += _fenced("yok", lambda: tier3_yok.harvest_institution(
                inst, log, raw_dir=data_dir / "raw" / "yok"))

        got = len(records) - n_before
        print(f"    {got} records")
        if got:
            harvested.add(inst.institution_en)

    n_raw = len(records)
    records, n_reviews = drop_reviews(records)
    if n_reviews:
        log.add("filter", "review-filter", "ok", records_returned=n_reviews,
                note="thesis review/referee-report records excluded (not theses)")
    records, n_nonthesis = drop_nonthesis(records)
    if n_nonthesis:
        log.add("filter", "type-filter", "ok", records_returned=n_nonthesis,
                note="records typed as articles/books/etc excluded (not theses)")
    records = dedupe(records)
    print(f"\n{n_raw} harvested -> {n_reviews} reviews + {n_nonthesis} non-thesis "
          f"records dropped -> {len(records)} after de-duplication")
    apply_market_flags(records, out_dir)
    df = write_outputs(records, out_dir)
    log.write_csv(out_dir / "harvest_log.csv")

    # YÖK gets its own log view on top of the shared one.
    yok_log = HarvestLog()
    yok_log.rows = [r for r in log.rows if r["source"] == "yok"]
    if yok_log.rows:
        yok_log.write_csv(out_dir / "yok_log.csv")

    write_gaps(targets, log, harvested, out_dir / "gaps.csv")

    failures = sum(1 for r in log.rows if r["outcome"] == "failed")
    preamble = ""
    if failures and df.empty:
        preamble = (
            "> **All sources failed — this run produced no records.** "
            "See the failure list below and `harvest_log.csv`. "
            "Zero rows here means *unreachable sources*, not *no theses*."
        )
    write_coverage_report(df, log, out_dir / "coverage_report.md", f"Phase {phase}", preamble)
    write_sample_rows(df, out_dir / "sample_rows.csv", 50)

    print(f"\n{len(df)} records -> {out_dir}/theses.parquet")
    print(f"{failures} failed source attempts -> {out_dir}/harvest_log.csv")
    return 0


def apply_market_flags(records: list[dict], out_dir: Path) -> None:
    """Flag every record and write the audit trail (which flags fired and
    which terms triggered them — how a bad stem gets spotted)."""
    matcher = FlagMatcher()
    audit_rows = []
    counts = {name: 0 for name in FLAG_NAMES}
    for rec in records:
        fired = matcher.flag_record(rec)
        rec["market_flags"] = sorted(fired)
        rec["flags_version"] = matcher.version
        for flag, terms in fired.items():
            counts[flag] += 1
            audit_rows.append({
                "id": rec["id"],
                "title": (rec.get("title_original") or "")[:80],
                "flag": flag,
                "terms": "|".join(terms),
            })
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "flag_audit.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "title", "flag", "terms"])
        w.writeheader()
        w.writerows(audit_rows)
    print(f"market flags (yaml v{matcher.version}): "
          + ", ".join(f"{k}={v}" for k, v in counts.items())
          + f" -> {out_dir / 'flag_audit.csv'}")


def reflag(out_dir: Path) -> int:
    """Re-apply the current thesis_domain_flags.yaml to an existing output
    directory without re-harvesting anything."""
    import pandas as pd

    from .outputs import write_outputs
    from .schema import COLUMNS

    df = pd.read_parquet(out_dir / "theses.parquet")
    for col in ("market_flags", "flags_version"):
        if col not in df.columns:
            df[col] = None
    records = df.to_dict("records")
    for rec in records:  # parquet round-trip: lists may come back as arrays
        for c in ("authors", "keywords", "national_flags", "domain_flags"):
            v = rec.get(c)
            rec[c] = list(v) if v is not None and not isinstance(v, list) else (v or [])
        for c in COLUMNS:
            rec.setdefault(c, None)
    apply_market_flags(records, out_dir)
    write_outputs(records, out_dir)
    print(f"{len(records)} records re-flagged in {out_dir}")
    return 0


def probe(base_url: str, data_dir: Path) -> int:
    """Try every known OAI path against a repository and report exactly what
    each answered, plus scan the homepage for hints. For finding the door
    when discovery fails."""
    import re

    from .http import HarvestError
    from .tier2_oaipmh import CANDIDATE_PATHS

    client = PoliteClient(cache_dir=data_dir / "raw")
    base = base_url.rstrip("/")
    print(f"Probing {base} ...\n")
    for path in CANDIDATE_PATHS + ["/server/api", "/rest", "/api"]:
        url = f"{base}{path}"
        try:
            res = client.get(url, params={"verb": "Identify"},
                             allow_error_status=True, use_cache=False)
        except HarvestError as e:
            print(f"  {path:35s} -> {e.kind}: {e}")
            continue
        body = res.text[:300].replace("\n", " ")
        looks_oai = "<OAI-PMH" in res.text[:2000] or "Identify" in res.text[:2000]
        print(f"  {path:35s} -> HTTP {res.status}  {'OAI!' if looks_oai else ''}")
        if res.status == 200 and not looks_oai:
            print(f"      starts with: {body[:120]}")
    print("\nScanning homepage for 'oai' mentions ...")
    try:
        res = client.get(base, allow_error_status=True, use_cache=False)
        hits = sorted(set(re.findall(r"[\w/\.:\-]*oai[\w/\.\-]*", res.text, re.IGNORECASE)))
        for h in hits[:15]:
            print(f"  {h}")
        if not hits:
            print("  (no mentions found)")
    except HarvestError as e:
        print(f"  homepage fetch failed: {e}")
    return 0


def inspect(out_dir: Path, data_dir: Path) -> int:
    """Print a quality snapshot of an existing output directory."""
    import json

    import pandas as pd

    df = pd.read_parquet(out_dir / "theses.parquet")
    print(f"{len(df)} records in {out_dir / 'theses.parquet'}\n")
    if len(df):
        print("By level:")
        print(df["level"].value_counts(dropna=False).to_string())
        unknown = df[df["level"] == "unknown"]
        if len(unknown):
            print("\nTop raw type strings among 'unknown'-level records "
                  "(what the sources actually call them — mapping candidates):")
            print(unknown["level_raw"].fillna("(empty)").value_counts().head(20).to_string())
            print("\n'unknown' records by institution:")
            print(unknown["institution"].value_counts().head(10).to_string())
        print("\nBy source:")
        print(df["source"].map(lambda s: str(s).split(":")[0]).value_counts().to_string())
        print("\nBy year (NaN = no parseable year, kept deliberately):")
        print(df["year"].value_counts(dropna=False).sort_index().to_string())
        print("\nFirst 25 rows (title/year/level):")
        view = df[["title_original", "year", "level"]].copy()
        view["title_original"] = view["title_original"].astype(str).str.slice(0, 70)
        print(view.head(25).to_string())
    for meta_file in sorted((data_dir / "meta").glob("*_oai_meta.json")):
        meta = json.loads(meta_file.read_text())
        sets = meta.get("sets", [])
        print(f"\n{meta_file.name}: {len(sets)} sets advertised by the repository:")
        for s in sets[:40]:
            print(f"  {s['setSpec']:55s} {s['setName'][:60]}")
        if len(sets) > 40:
            print(f"  ... and {len(sets) - 40} more")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="harvester")
    sub = p.add_subparsers(dest="cmd", required=True)

    runp = sub.add_parser("run", help="run a harvest phase")
    runp.add_argument("--phase", type=int, default=0)
    runp.add_argument("--out", type=Path, default=None)
    runp.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    runp.add_argument("--offline", action="store_true",
                      help="serve only from the raw cache; any uncached fetch is a logged failure")

    probep = sub.add_parser("probe", help="probe a repository base URL for its OAI endpoint")
    probep.add_argument("base_url")
    probep.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")

    sub.add_parser("yok-debug", help="open the YÖK search page and print what is on it")

    insp = sub.add_parser("inspect", help="summarise an existing output directory")
    insp.add_argument("--out", type=Path, default=PROJECT_ROOT / "output" / "phase0")
    insp.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")

    reflagp = sub.add_parser(
        "reflag", help="re-apply thesis_domain_flags.yaml to an existing dataset")
    reflagp.add_argument("--out", type=Path, default=PROJECT_ROOT / "output" / "phase1")

    args = p.parse_args()
    if args.cmd == "reflag":
        return reflag(args.out)
    if args.cmd == "probe":
        return probe(args.base_url, args.data)
    if args.cmd == "yok-debug":
        from . import tier3_yok
        tier3_yok.debug_page(PROJECT_ROOT / "output" / "yok_debug")
        return 0
    if args.cmd == "inspect":
        return inspect(args.out, args.data)
    out = args.out or PROJECT_ROOT / "output" / f"phase{args.phase}"
    return run(args.phase, out, args.data, offline=args.offline)


if __name__ == "__main__":
    raise SystemExit(main())
