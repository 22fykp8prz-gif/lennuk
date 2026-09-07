"""Command line interface.

Usage examples:
    python -m gas_plant_scraper list-sources
    python -m gas_plant_scraper run --countries EE,FI --max-docs 50
    python -m gas_plant_scraper run --sources cz_eia --no-download
    python -m gas_plant_scraper export --format csv --out data/catalog.csv
    python -m gas_plant_scraper report
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from .catalog import Catalog
from .crawler import SourceConfig, SourceCrawler
from .fetch import Fetcher

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"
DEFAULT_DATA_DIR = Path("data")


def load_sources(config_path: Path) -> list[SourceConfig]:
    with open(config_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return [SourceConfig.from_dict(s) for s in raw["sources"]]


def cmd_list_sources(args: argparse.Namespace) -> int:
    for src in load_sources(args.config):
        print(f"{src.country}  {src.id:24s} {src.name}")
        if src.notes:
            print(f"    märkus: {' '.join(src.notes.split())}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    sources = load_sources(args.config)
    if args.sources:
        wanted = {s.strip() for s in args.sources.split(",")}
        sources = [s for s in sources if s.id in wanted]
    if args.countries:
        wanted = {c.strip().upper() for c in args.countries.split(",")}
        sources = [s for s in sources if s.country in wanted]
    if not sources:
        print("Ühtegi allikat ei vasta filtritele.", file=sys.stderr)
        return 1

    data_dir = Path(args.out)
    catalog = Catalog(data_dir / "catalog.sqlite")
    fetcher = Fetcher(
        delay_seconds=args.delay,
        respect_robots=not args.ignore_robots,
    )

    total_docs = 0
    for src in sources:
        print(f"→ {src.country} / {src.id}: {src.name}")
        crawler = SourceCrawler(
            src,
            fetcher,
            catalog,
            data_dir,
            max_docs=args.max_docs,
            min_relevance=args.min_relevance,
            download=not args.no_download,
        )
        stats = crawler.run()
        total_docs += stats.documents_found
        print(
            f"   lehti: {stats.pages_fetched}, dokumente: {stats.documents_found} "
            f"(alla laetud {stats.documents_downloaded}), vigu: {stats.errors}, "
            f"tüübid: {stats.by_type or '-'}"
        )

    catalog.export_csv(data_dir / "catalog.csv")
    catalog.export_jsonl(data_dir / "catalog.jsonl")
    catalog.close()
    print(f"Kokku {total_docs} dokumenti. Kataloog: {data_dir/'catalog.csv'}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    catalog = Catalog(Path(args.data) / "catalog.sqlite")
    out = Path(args.out) if args.out else Path(args.data) / f"catalog.{args.format}"
    if args.format == "csv":
        n = catalog.export_csv(out)
    else:
        n = catalog.export_jsonl(out)
    catalog.close()
    print(f"{n} kirjet -> {out}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    catalog = Catalog(Path(args.data) / "catalog.sqlite")
    rows = catalog.rows()
    catalog.close()
    if not rows:
        print("Kataloog on tühi.")
        return 0
    by_country: dict[str, int] = {}
    by_bucket: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for row in rows:
        by_country[row["country"]] = by_country.get(row["country"], 0) + 1
        bucket = row["mw_bucket"] or "teadmata"
        by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
        for doc_type in (row["doc_types"] or "unclassified").split(","):
            by_type[doc_type] = by_type.get(doc_type, 0) + 1
    print(f"Dokumente kokku: {len(rows)}")
    print("Riigi järgi: ", dict(sorted(by_country.items())))
    print("MW-klassi järgi:", dict(sorted(by_bucket.items())))
    print("Tüübi järgi: ", dict(sorted(by_type.items(), key=lambda kv: -kv[1])))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gas_plant_scraper",
        description=(
            "Kogub avalikest planeeringu-, KMH- ja loaportaalidest "
            "gaasiturbiin- ja gaasimootorjaamade dokumente "
            "(joonised, seletuskirjad, ohutus, taristu)."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list-sources", help="Näita seadistatud allikaid")
    p_list.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p_list.set_defaults(func=cmd_list_sources)

    p_run = sub.add_parser("run", help="Käivita kogumine")
    p_run.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p_run.add_argument("--countries", help="nt EE,LV,FI (vaikimisi kõik)")
    p_run.add_argument("--sources", help="allika id-d komadega, nt cz_eia")
    p_run.add_argument("--out", default=str(DEFAULT_DATA_DIR), help="andmekaust")
    p_run.add_argument("--max-docs", type=int, default=100,
                       help="dokumentide ülempiir allika kohta")
    p_run.add_argument("--min-relevance", type=int, default=1,
                       help="mitu otsingusõna peab lingi kontekstis leiduma")
    p_run.add_argument("--delay", type=float, default=2.0,
                       help="viivitus sekundites sama hosti päringute vahel")
    p_run.add_argument("--no-download", action="store_true",
                       help="ainult katalogi, faile alla ei laeta")
    p_run.add_argument("--ignore-robots", action="store_true",
                       help="ära arvesta robots.txt-ga (kasuta vastutustundlikult)")
    p_run.set_defaults(func=cmd_run)

    p_exp = sub.add_parser("export", help="Ekspordi kataloog CSV/JSONL kujul")
    p_exp.add_argument("--data", default=str(DEFAULT_DATA_DIR))
    p_exp.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    p_exp.add_argument("--out")
    p_exp.set_defaults(func=cmd_export)

    p_rep = sub.add_parser("report", help="Kokkuvõte kogutud kataloogist")
    p_rep.add_argument("--data", default=str(DEFAULT_DATA_DIR))
    p_rep.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
