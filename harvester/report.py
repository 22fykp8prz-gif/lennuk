"""Coverage report: the document that says whether to trust any given slice."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .log import HarvestLog
from .schema import now_iso


def _share(series: pd.Series) -> str:
    if len(series) == 0:
        return "n/a"
    filled = series.map(lambda v: v not in (None, "", []) and not (isinstance(v, float) and pd.isna(v)))
    return f"{100 * filled.mean():.0f}%"


def write_coverage_report(
    df: pd.DataFrame,
    log: HarvestLog,
    out_path: Path,
    phase: str,
    preamble: str = "",
) -> None:
    lines = [
        f"# Coverage report — {phase}",
        "",
        f"Generated: {now_iso()}",
        "",
    ]
    if preamble:
        lines += [preamble, ""]

    lines += [f"**Total records: {len(df)}**", ""]

    if len(df):
        lines += [
            "## Per institution",
            "",
            "| country | institution | records | master's | year span | with abstract | with advisor | with full text | with English title |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for (country, institution), g in df.groupby(["country", "institution"], dropna=False):
            years = g["year"].dropna()
            span = f"{int(years.min())}–{int(years.max())}" if len(years) else "n/a"
            n_master = int((g["level"] == "master").sum())
            lines.append(
                f"| {country} | {institution} | {len(g)} | {n_master} | {span} | "
                f"{_share(g['abstract'])} | {_share(g['advisor'])} | "
                f"{_share(g['url_fulltext'])} | {_share(g['title_en'])} |"
            )
        lines += [
            "",
            "## Level breakdown",
            "",
            "| level | records |",
            "|---|---|",
            *[f"| {lvl} | {n} |" for lvl, n in df["level"].value_counts().items()],
            "",
            "## Relevance",
            "",
            f"- records with any domain flag: {int((df['domain_flags'].map(len) > 0).sum())}",
            f"- records with any national flag: {int((df['national_flags'].map(len) > 0).sum())}",
            f"- relevance_score >= 3: {int((df['relevance_score'] >= 3).sum())}",
            "",
        ]

    lines += ["## Source outcomes (harvest log summary)", ""]
    by_outcome: dict[str, int] = {}
    for row in log.rows:
        by_outcome[row["outcome"]] = by_outcome.get(row["outcome"], 0) + 1
    for outcome, n in sorted(by_outcome.items()):
        lines.append(f"- `{outcome}`: {n} log line(s)")
    failures = [r for r in log.rows if r["outcome"] == "failed"]
    if failures:
        lines += ["", "### Failures (every one is a coverage hole, not a zero)", ""]
        for r in failures:
            lines.append(f"- **{r['institution'] or r['source']}** — `{r['endpoint']}`: {r['error']}")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_sample_rows(df: pd.DataFrame, out_path: Path, n: int = 50) -> None:
    sample = df.head(0) if df.empty else df.sort_values(
        "relevance_score", ascending=False).head(n)
    out = sample.copy()
    for c in ("authors", "keywords", "national_flags", "domain_flags"):
        if c in out:
            out[c] = out[c].map(lambda v: "|".join(v) if isinstance(v, list) else v)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
