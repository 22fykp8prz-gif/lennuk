#!/usr/bin/env python3
"""End-to-end smoke test for seasonal_engine.py on synthetic data.

Builds a synthetic master.parquet (Main List stocks incl. two delisted names,
three OMX index series, volume/high/low columns, 2005-2026 business days) with
a planted January boost and momentum autocorrelation, runs the full engine,
and asserts that every workbook and fleet block is produced and that both
independent cross-checks pass.

Run from the repo root:  python tests/smoke_test.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import seasonal_engine  # noqa: E402


def build_synthetic(path: Path, seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2005-01-03", "2026-06-30")
    rows = []

    def walk(name, dates_slice, jan_boost=0.0, mom_factor=0.0, segment="Baltic Main List"):
        n = len(dates_slice)
        drift = rng.normal(0.0002, 0.0001)
        shocks = rng.normal(0, 0.015, n)
        rets = np.empty(n)
        prev = 0.0
        for i, d in enumerate(dates_slice):
            r = drift + shocks[i] + mom_factor * prev
            if jan_boost and (d.month == 1 or (d.month == 12 and d.day >= 15)):
                r += jan_boost
            rets[i] = r
            prev = 0.9 * prev + 0.1 * r
        px = 10 * np.exp(np.cumsum(rets))
        vol = rng.integers(0, 5000, n).astype(float)
        vol[rng.random(n) < 0.05] = 0            # some zero-volume days
        hi = px * (1 + np.abs(rng.normal(0, 0.008, n)))
        lo = px * (1 - np.abs(rng.normal(0, 0.008, n)))
        for d, p, v, h, l in zip(dates_slice, px, vol, hi, lo):
            rows.append((d, name, p, v, h, l, segment))

    for i in range(12):
        walk(f"TKM{i:02d}", dates, jan_boost=0.004 if i % 2 else 0.0,
             mom_factor=0.06)
    # delisted names (stop trading mid-sample) - survivorship coverage
    walk("DEAD1", dates[dates < "2015-06-01"], mom_factor=0.06)
    walk("DEAD2", dates[dates < "2019-03-01"], mom_factor=0.06)
    # secondary-list name that must be filtered out
    walk("SEC01", dates, segment="Secondary List")
    # index series
    for idx in ("OMXT", "OMXR", "OMXV"):
        walk(idx, dates, segment="index")

    df = pd.DataFrame(rows, columns=["date", "ticker", "close", "volume",
                                     "high", "low", "segment"])
    df.to_parquet(path, index=False)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="seasonal_smoke_"))
    data = tmp / "master.parquet"
    outdir = tmp / "results"
    build_synthetic(data)
    print(f"synthetic data: {data}")

    rc = seasonal_engine.main([
        "--theories", str(REPO / "theories_seasonal.json"),
        "--data", str(data),
        "--outdir", str(outdir),
    ])
    assert rc == 0

    expected = ["january_smallcap_effect", "halloween_effect",
                "momentum_12_1_long_only"]
    for tid in expected:
        xlsx = outdir / f"{tid}.xlsx"
        block = outdir / f"{tid}_fleet_block.md"
        assert xlsx.exists() and xlsx.stat().st_size > 1000, xlsx
        assert block.exists() and block.stat().st_size > 200, block
        sheets = pd.ExcelFile(xlsx).sheet_names
        assert "Parameters" in sheets and "Summary" in sheets, sheets
        print(f"  OK {tid}: sheets={sheets}")

    # Universe filtering: the secondary-list name must not reach the engine.
    md = seasonal_engine.load_master(str(data))
    assert "SEC01" not in set(md.stocks["ticker"]), "list filter failed"
    assert "DEAD1" in set(md.stocks["ticker"]), "delisted name lost"
    assert len(md.indices) == 3, md.indices.keys()
    assert "survivorship coverage looks plausible" in md.survivorship_note

    # Planted January boost should surface as a positive shifted-window edge.
    port = seasonal_engine.ew_daily_returns(md.stocks)
    res = seasonal_engine.run_monthly_seasonality(
        {"id": "x", "type": "monthly_seasonality"}, port)
    sh = res["variants"]["shifted_december_start"]
    assert sh["mean_window"] > sh["mean_baseline"], (
        sh["mean_window"], sh["mean_baseline"])
    print(f"  OK planted January edge detected: window {sh['mean_window']:.2%} "
          f"vs baseline {sh['mean_baseline']:.2%}, p={sh['p_fisher']:.4f}")

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
