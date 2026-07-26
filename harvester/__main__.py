"""CLI entrypoint.

    python -m harvester run --phase 0 [--out output/phase0] [--data data]

Phase 0: the three pilot institutions (pilot=1 in institutions.csv),
full pipeline end to end, then stop.
Phase 1: all tier-A institutions, tiers 1+2.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import PROJECT_ROOT, load_institutions
from .gaps import write_gaps
from .http import PoliteClient
from .log import HarvestLog
from .outputs import dedupe, write_outputs
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

        # Tier 1 — OpenAIRE first pass (not for YÖK-only institutions,
        # Turkish theses are not aggregated there in useful numbers).
        if inst.national_system != "yok":
            records += tier1_openaire.harvest_institution(inst, client, log)

        # Tier 2 — direct OAI-PMH where a repository is configured.
        if inst.repo_base_url:
            records += tier2_oaipmh.harvest_institution(
                inst, client, log, meta_dir=data_dir / "meta")

        # Tier 3 — YÖK browser module, its own log file as well.
        if inst.national_system == "yok":
            records += tier3_yok.harvest_institution(
                inst, log, raw_dir=data_dir / "raw" / "yok")

        got = len(records) - n_before
        print(f"    {got} records")
        if got:
            harvested.add(inst.institution_en)

    records = dedupe(records)
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


def main() -> int:
    p = argparse.ArgumentParser(prog="harvester")
    sub = p.add_subparsers(dest="cmd", required=True)
    runp = sub.add_parser("run", help="run a harvest phase")
    runp.add_argument("--phase", type=int, default=0)
    runp.add_argument("--out", type=Path, default=None)
    runp.add_argument("--data", type=Path, default=PROJECT_ROOT / "data")
    runp.add_argument("--offline", action="store_true",
                      help="serve only from the raw cache; any uncached fetch is a logged failure")
    args = p.parse_args()
    out = args.out or PROJECT_ROOT / "output" / f"phase{args.phase}"
    return run(args.phase, out, args.data, offline=args.offline)


if __name__ == "__main__":
    raise SystemExit(main())
