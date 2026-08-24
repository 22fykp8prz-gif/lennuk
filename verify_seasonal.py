#!/usr/bin/env python3
"""verify_seasonal.py — independent cross-check implementations.

Fleet standard: every portfolio return series must be reproduced by a second,
deliberately simple pandas implementation before results are accepted.
The functions here avoid the pivot/matrix code paths used by
seasonal_engine.py (plain groupby / explicit loops) so a bug in one path
cannot silently agree with itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TOLERANCE = 1e-9


class VerificationError(AssertionError):
    pass


def assert_series_match(engine: pd.Series, check: pd.Series, label: str,
                        tol: float = TOLERANCE) -> None:
    common = engine.index.intersection(check.index)
    if len(common) == 0:
        raise VerificationError(f"{label}: no overlapping index to compare")
    missing_engine = len(check.index.difference(engine.index))
    missing_check = len(engine.index.difference(check.index))
    if missing_engine or missing_check:
        raise VerificationError(
            f"{label}: index mismatch (engine missing {missing_engine}, "
            f"check missing {missing_check} entries)")
    diff = (engine.loc[common].astype(float)
            - check.loc[common].astype(float)).abs().max()
    if not np.isfinite(diff) or diff > tol:
        raise VerificationError(
            f"{label}: implementations disagree, max abs diff = {diff}")


def ew_daily_returns_simple(stocks: pd.DataFrame) -> pd.Series:
    """Equal-weight daily portfolio return via per-ticker groupby + date mean.

    Independent path: computes each ticker's daily return with a plain
    groupby-shift, then averages returns per date across tickers that have a
    valid return that day.
    """
    df = stocks[["date", "ticker", "close"]].dropna().copy()
    df = df.sort_values(["ticker", "date"])
    # collapse duplicate (ticker, date) rows the same way the engine's
    # pivot_table(aggfunc="last") does
    df = df.groupby(["ticker", "date"], as_index=False).last()
    df["ret"] = df.groupby("ticker")["close"].pct_change()
    port = df.dropna(subset=["ret"]).groupby("date")["ret"].mean()
    return port.sort_index()


def momentum_gross_simple(px_m: pd.DataFrame, *, lookback: int = 12,
                          skip: int = 1, reb_freq: str = "quarterly",
                          min_names: int = 6) -> pd.Series:
    """Gross holding-period returns of the top-tercile 12-1 portfolio,
    recomputed with explicit Python loops over names and months.

    No liquidity filter (matches the engine when no volume data is present;
    with volume data the engine's own eligibility list is compared only on
    the shared holding-period grid, so run this check on the same inputs).
    Returns a Series indexed by holding_start month period.
    """
    months = list(px_m.index)
    min_hist = lookback + skip
    if reb_freq == "monthly":
        rebs = [m for m in months[min_hist:-1]]
    else:
        rebs = [m for m in months[min_hist:-1] if m.month in (3, 6, 9, 12)]
    out = {}
    for k, t in enumerate(rebs):
        i = months.index(t)
        signals = {}
        for name in px_m.columns:
            p1 = px_m.iloc[i - skip][name]
            p0 = px_m.iloc[i - skip - lookback][name]
            if pd.notna(p1) and pd.notna(p0) and p0 != 0:
                signals[name] = p1 / p0 - 1
        if len(signals) < min_names:
            continue
        ranked = sorted(signals, key=lambda n: signals[n], reverse=True)
        n_top = max(1, int(np.ceil(len(ranked) / 3)))
        hold = ranked[:n_top]
        end_i = months.index(rebs[k + 1]) if k + 1 < len(rebs) else len(months) - 1
        wealth = 1.0
        for j in range(i + 1, end_i + 1):
            rets = []
            for name in hold:
                p_now, p_prev = px_m.iloc[j][name], px_m.iloc[j - 1][name]
                if pd.notna(p_now) and pd.notna(p_prev) and p_prev != 0:
                    rets.append(p_now / p_prev - 1)
            invested = len(rets) / n_top
            month_ret = (sum(rets) / len(rets)) * invested if rets else 0.0
            wealth *= 1 + month_ret
        out[months[min(i + 1, len(months) - 1)]] = wealth - 1
    return pd.Series(out).sort_index()
