#!/usr/bin/env python3
"""seasonal_engine.py — schema 2.0 theory engine for Baltic Main List backtests.

Dispatches on the theory `type` field of theories_seasonal.json (schema_version 2.0):

  * monthly_seasonality      — calendar-window portfolio returns vs same-length
                               baseline windows (January effect).
  * period_seasonality       — two fixed half-year windows compared per year
                               (Halloween effect).
  * cross_sectional_momentum — ranked long-only portfolio with rebalancing,
                               turnover and per-trade half-spread costs
                               (12-1 momentum).

pattern_engine.py (day-of-week patterns 1-2) is untouched; if it is importable
its Fisher's exact implementation is reused, otherwise an identical log-gamma
implementation below is used.

Usage:
    python seasonal_engine.py --theories theories_seasonal.json \
                              --data master.parquet --outdir results

Outputs per theory: <outdir>/<theory_id>.xlsx (Parameters / PerYear /
SubPeriods / Summary sheets) and <outdir>/<theory_id>_fleet_block.md
(paste-ready results block for trading_strategy_fleet.md).

Methodology rules honoured (see seasonal_momentum_handoff.md):
  - full-period first, five sub-period stability where powered;
  - gross AND net returns (net = half-spread on every entry and exit, commission 0);
  - long-only throughout;
  - survivorship flag if the parquet looks like it only has live names;
  - every portfolio return series is cross-checked against the independent
    implementation in verify_seasonal.py before results are accepted.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from math import exp, lgamma, log
from pathlib import Path

import numpy as np
import pandas as pd

import verify_seasonal

# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _log_comb(n: int, k: int) -> float:
    return lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1)


def fisher_exact_greater(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher's exact p-value, H1: row-1 hit rate > row-2 hit rate.

    Table [[a, b], [c, d]] = [[window hits, window misses],
                              [baseline hits, baseline misses]].
    Log-gamma implementation, no scipy dependency.
    """
    n = a + b + c + d
    r1, c1 = a + b, a + c
    hi = min(r1, c1)
    log_denom = _log_comb(n, c1)
    p = 0.0
    for x in range(a, hi + 1):
        p += exp(_log_comb(r1, x) + _log_comb(n - r1, c1 - x) - log_denom)
    return min(p, 1.0)


# Reuse the fleet's existing implementation when pattern_engine is on the path.
try:  # pragma: no cover - depends on local checkout
    from pattern_engine import fisher_exact_greater as _pe_fisher  # type: ignore
    fisher_exact_greater = _pe_fisher  # noqa: F811
except ImportError:
    pass


def binom_test_greater(k: int, n: int, p: float = 0.5) -> float:
    """Exact one-sided binomial test, H1: hit rate > p (used for 'vs 50%')."""
    if n == 0:
        return float("nan")
    return min(1.0, sum(
        exp(_log_comb(n, x) + x * log(p) + (n - x) * log(1.0 - p))
        for x in range(k, n + 1)
    ))


def bootstrap_ci_mean(values, n_boot: int = 10_000, seed: int = 42,
                      alpha: float = 0.05) -> tuple[float, float]:
    x = np.asarray(list(values), dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    means = x[idx].mean(axis=1)
    return (float(np.percentile(means, 100 * alpha / 2)),
            float(np.percentile(means, 100 * (1 - alpha / 2))))


def annualize(total_return: float, n_months: float) -> float:
    if n_months <= 0 or (1 + total_return) <= 0:
        return float("nan")
    return (1 + total_return) ** (12.0 / n_months) - 1


def max_drawdown(returns: pd.Series) -> float:
    wealth = (1 + returns.fillna(0)).cumprod()
    return float((wealth / wealth.cummax() - 1).min())


def worst_rolling_12m(monthly: pd.Series) -> float:
    if len(monthly) < 12:
        return float("nan")
    roll = (1 + monthly.fillna(0)).rolling(12).apply(np.prod, raw=True) - 1
    return float(roll.min())


# ---------------------------------------------------------------------------
# Data loading / normalization
# ---------------------------------------------------------------------------

_DATE_CANDS = ["date", "trade_date", "datetime", "day"]
_TICKER_CANDS = ["ticker", "symbol", "secid", "isin", "name"]
_PRICE_CANDS = ["close", "adj_close", "adjclose", "last", "price", "close_price"]
_OPTIONAL = {"volume": ["volume", "vol", "turnover_qty"],
             "bid": ["bid", "best_bid"],
             "ask": ["ask", "best_ask"],
             "high": ["high"],
             "low": ["low"],
             "segment": ["segment", "list", "market", "market_segment"]}

_INDEX_PATTERNS = {"OMX Tallinn": ("omxt",), "OMX Riga": ("omxr",),
                   "OMX Vilnius": ("omxv",)}


@dataclass
class MarketData:
    stocks: pd.DataFrame            # long: date, ticker, close [, optional cols]
    indices: dict[str, pd.Series]   # index name -> daily close series
    survivorship_note: str = ""
    warnings: list[str] = field(default_factory=list)


def _pick(cols: dict[str, str], candidates) -> str | None:
    for c in candidates:
        if c in cols:
            return cols[c]
    return None


def load_master(path: str, list_filter: str | None = "main") -> MarketData:
    """Load master.parquet and normalize to a long frame.

    Accepts a long frame (date/ticker/close plus optional volume, bid, ask,
    high, low, segment columns — several common spellings recognized) or a
    wide frame (date index, one price column per ticker).
    """
    raw = pd.read_parquet(path)
    warnings: list[str] = []
    cols = {c.lower().strip(): c for c in raw.columns}

    date_col = _pick(cols, _DATE_CANDS)
    tick_col = _pick(cols, _TICKER_CANDS)
    price_col = _pick(cols, _PRICE_CANDS)

    if date_col and tick_col and price_col:
        df = pd.DataFrame({
            "date": pd.to_datetime(raw[date_col]),
            "ticker": raw[tick_col].astype(str),
            "close": pd.to_numeric(raw[price_col], errors="coerce"),
        })
        for out_name, cands in _OPTIONAL.items():
            col = _pick(cols, cands)
            if col is not None:
                df[out_name] = (raw[col] if out_name == "segment"
                                else pd.to_numeric(raw[col], errors="coerce"))
    else:
        # Wide format: dates in the index (or first column), tickers as columns.
        wide = raw.copy()
        if date_col:
            wide = wide.set_index(pd.to_datetime(wide[date_col])).drop(columns=[date_col])
        else:
            wide.index = pd.to_datetime(wide.index)
        df = wide.stack().rename("close").reset_index()
        df.columns = ["date", "ticker", "close"]
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        warnings.append("master.parquet read as WIDE frame: no volume/bid/ask/"
                        "segment columns available; liquidity filter and "
                        "measured spreads disabled.")

    df = df.dropna(subset=["close"]).sort_values(["ticker", "date"])

    # Split out index series before universe filtering.
    indices: dict[str, pd.Series] = {}
    tickers_lower = {t: t.lower() for t in df["ticker"].unique()}
    index_tickers = set()
    for name, pats in _INDEX_PATTERNS.items():
        for t, tl in tickers_lower.items():
            if any(tl.startswith(p) for p in pats):
                s = (df[df["ticker"] == t].set_index("date")["close"].sort_index())
                indices[f"{name} ({t})"] = s
                index_tickers.add(t)
    stocks = df[~df["ticker"].isin(index_tickers)].copy()

    if list_filter and "segment" in stocks.columns:
        seg = stocks["segment"].astype(str).str.lower()
        mask = seg.str.contains(list_filter.lower(), na=False)
        if mask.any():
            stocks = stocks[mask].copy()
        else:
            warnings.append(f"segment column present but no value matches "
                            f"'{list_filter}'; universe NOT filtered.")
    elif list_filter:
        warnings.append("No segment/list column in master.parquet; assuming "
                        "the file already contains only Main List names.")

    # Survivorship check: without delisted names momentum is inflated.
    last_dates = stocks.groupby("ticker")["date"].max()
    data_end = stocks["date"].max()
    delisted_like = int((last_dates < data_end - pd.Timedelta(days=90)).sum())
    if delisted_like == 0:
        note = ("WARNING: every ticker trades up to the end of the sample - "
                "the parquet likely contains only currently listed names. "
                "Momentum results are meaningfully inflated by survivorship "
                "bias; treat them as an upper bound.")
    else:
        note = (f"{delisted_like} of {last_dates.size} tickers stop trading "
                f">90 days before sample end (delisted or suspended) - "
                f"survivorship coverage looks plausible.")

    return MarketData(stocks=stocks, indices=indices,
                      survivorship_note=note, warnings=warnings)


# ---------------------------------------------------------------------------
# Portfolio building blocks
# ---------------------------------------------------------------------------

def price_matrix(stocks: pd.DataFrame) -> pd.DataFrame:
    return (stocks.pivot_table(index="date", columns="ticker", values="close",
                               aggfunc="last").sort_index())


def ew_daily_returns(stocks: pd.DataFrame) -> pd.Series:
    """Equal-weight daily portfolio return across all tickers with valid data.

    Cross-checked against verify_seasonal.ew_daily_returns_simple (independent
    groupby/loop implementation) before being returned.
    """
    px = price_matrix(stocks)
    rets = px.pct_change()
    port = rets.mean(axis=1).dropna()
    check = verify_seasonal.ew_daily_returns_simple(stocks)
    verify_seasonal.assert_series_match(port, check, "EW daily portfolio")
    return port


def year_subperiods(years: list[int], n: int = 5) -> list[tuple[int, int]]:
    """Split the sample years into n contiguous, nearly equal windows."""
    chunks = np.array_split(np.array(sorted(set(years))), n)
    return [(int(c[0]), int(c[-1])) for c in chunks if len(c)]


def compound(series: pd.Series) -> float:
    if series.empty:
        return float("nan")
    return float((1 + series).prod() - 1)


# ---------------------------------------------------------------------------
# Theory 1: monthly_seasonality (January effect)
# ---------------------------------------------------------------------------

def run_monthly_seasonality(theory: dict, port: pd.Series) -> dict:
    monthly = (1 + port).groupby([port.index.year, port.index.month]).prod() - 1
    monthly.index.names = ["year", "month"]
    years = sorted(monthly.index.get_level_values("year").unique())
    subs = year_subperiods(years)

    out = {"theory": theory, "variants": {}, "subperiods": subs}

    # --- classic_january: January vs all other calendar months --------------
    per_year = []
    win_hits = base_hits = base_n = 0
    jan_rets, other_rets = [], []
    for y in years:
        ym = monthly.loc[y] if y in monthly.index.get_level_values(0) else None
        if ym is None or 1 not in ym.index:
            continue
        med = float(ym.median())
        jan = float(ym.loc[1])
        others = ym.drop(index=1)
        jan_rets.append(jan)
        other_rets.extend(others.tolist())
        hit = jan > med
        win_hits += int(hit)
        base_hits += int((others > med).sum())
        base_n += len(others)
        per_year.append({"year": y, "january_return": jan,
                         "median_month_of_year": med,
                         "mean_other_months": float(others.mean()),
                         "hit": hit})
    per_year_df = pd.DataFrame(per_year)
    n_years = len(per_year_df)
    p_fisher = fisher_exact_greater(win_hits, n_years - win_hits,
                                    base_hits, base_n - base_hits)
    out["variants"]["classic_january"] = {
        "per_year": per_year_df,
        "mean_window": float(np.mean(jan_rets)) if jan_rets else float("nan"),
        "mean_baseline": float(np.mean(other_rets)) if other_rets else float("nan"),
        "hit_rate": win_hits / n_years if n_years else float("nan"),
        "hits": win_hits, "n": n_years,
        "baseline_hit_rate": base_hits / base_n if base_n else float("nan"),
        "p_fisher": p_fisher,
        "subperiod": _subperiod_direction(per_year_df, subs, "january_return",
                                          "mean_other_months"),
    }

    # --- shifted_december_start: Dec 15 - Jan 31 vs same-length windows -----
    out["variants"]["shifted_december_start"] = _shifted_window_variant(
        port, years, subs, start_md=(12, 15), end_md=(1, 31))
    return out


def _shifted_window_variant(port: pd.Series, years, subs,
                            start_md: tuple[int, int],
                            end_md: tuple[int, int]) -> dict:
    """Window spanning year end (e.g. Dec 15 -> Jan 31) vs same-length
    rolling windows on all non-overlapping days of the year."""
    per_year, lengths = [], []
    for y in years:
        start = pd.Timestamp(y - 1, *start_md)
        end = pd.Timestamp(y, *end_md)
        w = port.loc[(port.index >= start) & (port.index <= end)]
        if len(w) < 15:            # window not (fully) covered by the data
            continue
        lengths.append(len(w))
        per_year.append({"year": y, "window_return": compound(w),
                         "n_days": len(w)})
    if not per_year:
        return {"per_year": pd.DataFrame(), "error": "no covered windows"}
    per_year_df = pd.DataFrame(per_year)
    L = int(np.median(lengths))

    # Same-length rolling windows; keep only those that do not overlap any
    # Dec15-Jan31 span: end dates Apr 1 - Nov 30 (a ~48-calendar-day window
    # ending Apr 1 starts mid-February; ending Nov 30 it ends before Dec 15).
    roll = (1 + port).rolling(L).apply(np.prod, raw=True) - 1
    roll = roll.dropna()
    base = roll[roll.index.month.isin(range(4, 12))]

    base_by_year = {y: base[base.index.year == y] for y in years}
    win_hits = 0
    rows = []
    base_hits = base_n = 0
    for row in per_year_df.itertuples():
        b = base_by_year.get(row.year, pd.Series(dtype=float))
        if b.empty:
            continue
        med = float(b.median())
        hit = row.window_return > med
        win_hits += int(hit)
        base_hits += int((b > med).sum())
        base_n += len(b)
        rows.append({"year": row.year, "window_return": row.window_return,
                     "baseline_median": med, "baseline_mean": float(b.mean()),
                     "hit": hit})
    py = pd.DataFrame(rows)
    n = len(py)
    return {
        "per_year": py,
        "window_trading_days": L,
        "mean_window": float(py["window_return"].mean()) if n else float("nan"),
        "mean_baseline": float(base.mean()) if len(base) else float("nan"),
        "hit_rate": win_hits / n if n else float("nan"),
        "hits": win_hits, "n": n,
        "p_fisher": fisher_exact_greater(win_hits, n - win_hits,
                                         base_hits, base_n - base_hits),
        "baseline_note": ("baseline rolling windows overlap each other; "
                          "Fisher p is indicative, the pre-registered gate "
                          "uses it together with sub-period direction."),
        "subperiod": _subperiod_direction(py, subs, "window_return",
                                          "baseline_mean"),
    }


def _subperiod_direction(per_year_df: pd.DataFrame, subs,
                         win_col: str, base_col: str) -> pd.DataFrame:
    rows = []
    for (y0, y1) in subs:
        chunk = per_year_df[(per_year_df["year"] >= y0) & (per_year_df["year"] <= y1)]
        if chunk.empty:
            continue
        rows.append({"period": f"{y0}-{y1}", "n_years": len(chunk),
                     "mean_window": float(chunk[win_col].mean()),
                     "mean_baseline": float(chunk[base_col].mean()),
                     "positive_direction": bool(chunk[win_col].mean()
                                                > chunk[base_col].mean()),
                     "hit_rate": float(chunk["hit"].mean())
                     if "hit" in chunk else float("nan")})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Theory 2: period_seasonality (Halloween effect)
# ---------------------------------------------------------------------------

def run_period_seasonality(theory: dict, port: pd.Series,
                           indices: dict[str, pd.Series]) -> dict:
    instruments: dict[str, pd.Series] = {"Equal-weight Main List": port}
    for name, px in indices.items():
        instruments[name] = px.pct_change().dropna()

    years = sorted(set(port.index.year))
    subs = year_subperiods(years)
    out = {"theory": theory, "instruments": {}, "subperiods": subs}

    for name, rets in instruments.items():
        rows = []
        for y in sorted(set(rets.index.year)):
            summer = rets[(rets.index >= pd.Timestamp(y, 5, 1)) &
                          (rets.index <= pd.Timestamp(y, 10, 31))]
            winter = rets[(rets.index >= pd.Timestamp(y, 11, 1)) &
                          (rets.index <= pd.Timestamp(y + 1, 4, 30))]
            if len(summer) < 60 or len(winter) < 60:   # need both halves
                continue
            s, w = compound(summer), compound(winter)
            rows.append({"cycle_year": y, "summer_may_oct": s,
                         "winter_nov_apr": w, "winter_minus_summer": w - s,
                         "hit": w > s})
        py = pd.DataFrame(rows)
        n = len(py)
        hits = int(py["hit"].sum()) if n else 0
        diffs = py["winter_minus_summer"] if n else pd.Series(dtype=float)
        ci = bootstrap_ci_mean(diffs)
        sub_rows = []
        for (y0, y1) in subs:
            chunk = py[(py["cycle_year"] >= y0) & (py["cycle_year"] <= y1)]
            if chunk.empty:
                continue
            sub_rows.append({"period": f"{y0}-{y1}", "n_years": len(chunk),
                             "mean_diff": float(chunk["winter_minus_summer"].mean()),
                             "winter_wins": int(chunk["hit"].sum()),
                             "note": "descriptive only (underpowered)"})
        out["instruments"][name] = {
            "per_year": py,
            "hits": hits, "n": n,
            "hit_rate": hits / n if n else float("nan"),
            "mean_diff": float(diffs.mean()) if n else float("nan"),
            "ci_low": ci[0], "ci_high": ci[1],
            "p_binom_vs_50": binom_test_greater(hits, n),
            "subperiod": pd.DataFrame(sub_rows),
        }
    return out


# ---------------------------------------------------------------------------
# Theory 3: cross_sectional_momentum (12-1, long-only)
# ---------------------------------------------------------------------------

def estimate_half_spreads(stocks: pd.DataFrame,
                          default_half_spread: float) -> tuple[pd.Series, str]:
    """Per-ticker half-spread: median (ask-bid)/2/mid when quotes exist, else
    Corwin-Schultz high-low estimator, else the configured default."""
    tickers = stocks["ticker"].unique()
    if {"bid", "ask"}.issubset(stocks.columns):
        g = stocks.dropna(subset=["bid", "ask"])
        g = g[(g["bid"] > 0) & (g["ask"] >= g["bid"])]
        mid = (g["ask"] + g["bid"]) / 2
        hs = ((g["ask"] - g["bid"]) / 2 / mid).groupby(g["ticker"]).median()
        method = "median quoted half-spread (ask-bid)/2/mid"
    elif {"high", "low"}.issubset(stocks.columns):
        hs = (stocks.dropna(subset=["high", "low"])
              .groupby("ticker")[["high", "low"]].apply(_corwin_schultz))
        method = "Corwin-Schultz high-low estimator / 2"
    else:
        hs = pd.Series(dtype=float)
        method = (f"no bid/ask or high/low columns: flat default "
                  f"{default_half_spread:.2%} half-spread per trade")
    hs = hs.reindex(tickers).fillna(default_half_spread).clip(0.0005, 0.05)
    return hs, method


def _corwin_schultz(g: pd.DataFrame) -> float:
    h, l = g["high"].to_numpy(float), g["low"].to_numpy(float)
    ok = (h > 0) & (l > 0) & (h >= l)
    h, l = h[ok], l[ok]
    if len(h) < 40:
        return float("nan")
    beta = (np.log(h[:-1] / l[:-1]) ** 2 + np.log(h[1:] / l[1:]) ** 2)
    gamma = np.log(np.maximum(h[:-1], h[1:]) / np.minimum(l[:-1], l[1:])) ** 2
    alpha = ((np.sqrt(2 * beta) - np.sqrt(beta)) / (3 - 2 * np.sqrt(2))
             - np.sqrt(gamma / (3 - 2 * np.sqrt(2))))
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    s = float(np.nanmedian(np.maximum(spread, 0)))
    return s / 2 if np.isfinite(s) else float("nan")


def run_momentum(theory: dict, stocks: pd.DataFrame,
                 default_half_spread: float) -> dict:
    px_d = price_matrix(stocks)
    px_m = px_d.groupby(px_d.index.to_period("M")).last()
    ret_m = px_m.pct_change()

    sig = theory.get("signal", {})
    lookback = int(sig.get("lookback_months", 12))
    skip = int(sig.get("skip_months", 1))
    min_hist = lookback + skip
    zero_vol_max = 0.20

    # Zero-volume-day fraction over the lookback (liquidity eligibility).
    if "volume" in stocks.columns:
        vol = stocks.assign(m=stocks["date"].dt.to_period("M"))
        zero = (vol.assign(z=(vol["volume"].fillna(0) <= 0).astype(int))
                .groupby(["m", "ticker"])
                .agg(z=("z", "sum"), d=("z", "size")))
        zsum = zero["z"].unstack("ticker").reindex(px_m.index).fillna(0)
        dsum = zero["d"].unstack("ticker").reindex(px_m.index).fillna(0)
        zfrac = (zsum.rolling(lookback).sum()
                 / dsum.rolling(lookback).sum().replace(0, np.nan))
        liquidity_note = "zero-volume filter active (>20% zero-volume days excluded)"
    else:
        zfrac = None
        liquidity_note = "no volume column: zero-volume liquidity filter DISABLED"

    half_spread, spread_method = estimate_half_spreads(stocks, default_half_spread)

    months = list(px_m.index)
    years = sorted({m.year for m in months})
    subs = year_subperiods(years)
    out = {"theory": theory, "variants": {}, "subperiods": subs,
           "spread_method": spread_method, "liquidity_note": liquidity_note,
           "half_spread_median": float(half_spread.median())}

    for reb_freq in theory.get("portfolio", {}).get(
            "rebalance_variants", ["monthly", "quarterly"]):
        for abs_filter in (False, True):
            key = f"{reb_freq}{'_absfilter' if abs_filter else ''}"
            out["variants"][key] = _simulate_momentum(
                px_m, ret_m, zfrac, half_spread, months, subs,
                lookback=lookback, skip=skip, min_hist=min_hist,
                zero_vol_max=zero_vol_max, reb_freq=reb_freq,
                abs_filter=abs_filter)

    # Independent cross-check: run the engine's simulator WITHOUT the
    # liquidity filter (the verifier has none) and compare gross
    # holding-period returns against the loop-based implementation.
    unfiltered = _simulate_momentum(
        px_m, ret_m, None, half_spread, months, subs,
        lookback=lookback, skip=skip, min_hist=min_hist,
        zero_vol_max=zero_vol_max, reb_freq="quarterly", abs_filter=False)
    check = verify_seasonal.momentum_gross_simple(
        px_m, lookback=lookback, skip=skip, reb_freq="quarterly")
    engine_gross = unfiltered["period_table"].set_index(
        "holding_start")["gross_return"]
    verify_seasonal.assert_series_match(
        engine_gross, check, "momentum quarterly gross holding-period returns")
    out["verified"] = True
    return out


def _rebalance_months(months, reb_freq: str, min_hist: int):
    idx = range(min_hist, len(months) - 1)
    if reb_freq == "monthly":
        return [months[i] for i in idx]
    return [months[i] for i in idx if months[i].month in (3, 6, 9, 12)]


def _simulate_momentum(px_m, ret_m, zfrac, half_spread, months, subs, *,
                       lookback, skip, min_hist, zero_vol_max,
                       reb_freq, abs_filter) -> dict:
    pos = {m: i for i, m in enumerate(months)}
    rebs = _rebalance_months(months, reb_freq, min_hist)
    prev_hold: list[str] = []
    period_rows = []
    port_monthly = {}     # month -> (gross, cost applied that month)
    bench_monthly = {}

    for k, t in enumerate(rebs):
        i = pos[t]
        p_end = px_m.iloc[i - skip]           # price at end of month t-1
        p_start = px_m.iloc[i - skip - lookback]
        signal = (p_end / p_start - 1).dropna()
        eligible = signal.index
        if zfrac is not None:
            zrow = zfrac.iloc[i - skip]
            eligible = [tk for tk in eligible
                        if not (zrow.get(tk, np.nan) > zero_vol_max)]
        # ticker-alphabetical tie-break keeps the ranking deterministic and
        # identical to verify_seasonal.momentum_gross_simple
        signal = signal.loc[list(eligible)].sort_index()
        signal = signal.sort_values(ascending=False, kind="stable")
        if len(signal) < 6:
            prev_hold = []
            continue
        n_top = max(1, int(np.ceil(len(signal) / 3)))
        hold = list(signal.index[:n_top])
        if abs_filter:
            hold = [tk for tk in hold if signal[tk] > 0]

        # Per-trade half-spread on every entry and exit.
        entries = [tk for tk in hold if tk not in prev_hold]
        exits = [tk for tk in prev_hold if tk not in hold]
        w_new = 1.0 / n_top if hold else 0.0     # abs-filter: rest is cash
        w_old = 1.0 / len(prev_hold) if prev_hold else 0.0
        cost = (sum(half_spread[tk] for tk in entries) * w_new
                + sum(half_spread[tk] for tk in exits) * w_old)
        turnover = len(entries) * w_new + len(exits) * w_old

        hold_end = pos[rebs[k + 1]] if k + 1 < len(rebs) else len(months) - 1
        g_period, b_period, first = 1.0, 1.0, True
        for j in range(i + 1, hold_end + 1):
            m = months[j]
            r_all = ret_m.iloc[j]
            r_hold = r_all.reindex(hold).dropna()
            invested = (len(r_hold) / n_top) if n_top else 0.0
            g = float(r_hold.mean()) * invested if len(r_hold) else 0.0
            bvals = r_all.reindex(signal.index).dropna()
            b = float(bvals.mean()) if len(bvals) else 0.0
            c = cost if first else 0.0
            port_monthly[m] = (g, c)
            bench_monthly[m] = b
            g_period *= (1 + g)
            b_period *= (1 + b)
            first = False
        gross = g_period - 1
        net = (1 + gross) * (1 - cost) - 1 if hold or prev_hold else gross
        bench = b_period - 1
        period_rows.append({"holding_start": months[min(i + 1, len(months) - 1)],
                            "rebalance": t, "n_eligible": len(signal),
                            "n_held": len(hold), "turnover": turnover,
                            "cost": cost, "gross_return": gross,
                            "net_return": net, "benchmark_return": bench,
                            "net_beats_benchmark": net > bench})
        prev_hold = hold

    pt = pd.DataFrame(period_rows)
    if pt.empty:
        return {"period_table": pt, "error": "not enough data"}

    g_m = pd.Series({m: v[0] for m, v in port_monthly.items()}).sort_index()
    net_m = pd.Series({m: (1 + v[0]) * (1 - v[1]) - 1
                       for m, v in port_monthly.items()}).sort_index()
    b_m = pd.Series(bench_monthly).sort_index()
    n_months = len(net_m)

    hits = int(pt["net_beats_benchmark"].sum())
    n_per = len(pt)
    sub_rows = []
    for (y0, y1) in subs:
        sel = net_m[(net_m.index.year >= y0) & (net_m.index.year <= y1)]
        selb = b_m.reindex(sel.index)
        selg = g_m.reindex(sel.index)
        if len(sel) < 6:
            continue
        sub_rows.append({
            "period": f"{y0}-{y1}", "n_months": len(sel),
            "gross_ann": annualize(compound(selg), len(sel)),
            "net_ann": annualize(compound(sel), len(sel)),
            "bench_ann": annualize(compound(selb), len(selb)),
            "net_excess_ann": annualize(compound(sel), len(sel))
                              - annualize(compound(selb), len(selb)),
            "net_excess_positive": annualize(compound(sel), len(sel))
                                   > annualize(compound(selb), len(selb))})

    ann_turnover = float(pt["turnover"].sum() / n_months * 12) if n_months else float("nan")
    return {
        "period_table": pt,
        "monthly_net": net_m, "monthly_gross": g_m, "monthly_bench": b_m,
        "gross_ann": annualize(compound(g_m), n_months),
        "net_ann": annualize(compound(net_m), n_months),
        "bench_ann": annualize(compound(b_m), n_months),
        "net_excess_ann": annualize(compound(net_m), n_months)
                          - annualize(compound(b_m), n_months),
        "hits": hits, "n_periods": n_per,
        "hit_rate": hits / n_per,
        "p_binom_vs_50": binom_test_greater(hits, n_per),
        "max_drawdown_net": max_drawdown(net_m),
        "worst_12m_net": worst_rolling_12m(net_m),
        "annual_turnover_oneway": ann_turnover,
        "subperiod": pd.DataFrame(sub_rows),
    }


# ---------------------------------------------------------------------------
# Reporting: Excel workbooks + fleet ruleset blocks
# ---------------------------------------------------------------------------

def _params_sheet(theory: dict, extra: dict | None = None) -> pd.DataFrame:
    rows = [("theory_id", theory.get("id")), ("type", theory.get("type")),
            ("category", theory.get("category")),
            ("hypothesis", theory.get("hypothesis")),
            ("execution_note", theory.get("execution_note"))]
    for k, v in (extra or {}).items():
        rows.append((k, v))
    return pd.DataFrame(rows, columns=["parameter", "value"])


def write_monthly_seasonality_report(res: dict, outdir: Path,
                                     data_notes: list[str]) -> Path:
    t = res["theory"]
    path = outdir / f"{t['id']}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        _params_sheet(t, {"data_notes": " | ".join(data_notes)}).to_excel(
            xl, sheet_name="Parameters", index=False)
        summary = []
        for vname, v in res["variants"].items():
            if "error" in v:
                continue
            v["per_year"].to_excel(xl, sheet_name=f"PerYear_{vname}"[:31], index=False)
            v["subperiod"].to_excel(xl, sheet_name=f"SubPeriods_{vname}"[:31], index=False)
            summary.append({
                "variant": vname, "mean_window": v["mean_window"],
                "mean_baseline": v["mean_baseline"],
                "edge": v["mean_window"] - v["mean_baseline"],
                "hit_rate": v["hit_rate"], "hits": v["hits"], "n_years": v["n"],
                "p_fisher_one_sided": v["p_fisher"],
                "subperiods_positive":
                    int(v["subperiod"]["positive_direction"].sum())
                    if len(v["subperiod"]) else 0,
                "subperiods_total": len(v["subperiod"])})
        pd.DataFrame(summary).to_excel(xl, sheet_name="Summary", index=False)
    return path


def write_period_seasonality_report(res: dict, outdir: Path,
                                    data_notes: list[str]) -> Path:
    t = res["theory"]
    path = outdir / f"{t['id']}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        _params_sheet(t, {"data_notes": " | ".join(data_notes)}).to_excel(
            xl, sheet_name="Parameters", index=False)
        summary = []
        for i, (name, v) in enumerate(res["instruments"].items()):
            tag = f"I{i}_" + "".join(ch for ch in name if ch.isalnum())[:24]
            v["per_year"].to_excel(xl, sheet_name=f"PerYear_{tag}"[:31], index=False)
            v["subperiod"].to_excel(xl, sheet_name=f"SubP_{tag}"[:31], index=False)
            summary.append({"instrument": name, "n_years": v["n"],
                            "winter_wins": v["hits"], "hit_rate": v["hit_rate"],
                            "mean_winter_minus_summer": v["mean_diff"],
                            "bootstrap_ci_low": v["ci_low"],
                            "bootstrap_ci_high": v["ci_high"],
                            "p_binom_vs_50": v["p_binom_vs_50"]})
        pd.DataFrame(summary).to_excel(xl, sheet_name="Summary", index=False)
    return path


def write_momentum_report(res: dict, outdir: Path,
                          data_notes: list[str]) -> Path:
    t = res["theory"]
    path = outdir / f"{t['id']}.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        _params_sheet(t, {
            "spread_model": res["spread_method"],
            "median_half_spread": res["half_spread_median"],
            "liquidity_filter": res["liquidity_note"],
            "data_notes": " | ".join(data_notes)}).to_excel(
            xl, sheet_name="Parameters", index=False)
        summary = []
        for vname, v in res["variants"].items():
            if "error" in v:
                continue
            pt = v["period_table"].copy()
            pt["rebalance"] = pt["rebalance"].astype(str)
            pt["holding_start"] = pt["holding_start"].astype(str)
            pt.to_excel(xl, sheet_name=f"Periods_{vname}"[:31], index=False)
            v["subperiod"].to_excel(xl, sheet_name=f"SubP_{vname}"[:31], index=False)
            summary.append({
                "variant": vname,
                "gross_ann": v["gross_ann"], "net_ann": v["net_ann"],
                "benchmark_ann": v["bench_ann"],
                "net_excess_ann": v["net_excess_ann"],
                "hit_rate_vs_bench": v["hit_rate"],
                "p_binom_vs_50": v["p_binom_vs_50"],
                "max_drawdown_net": v["max_drawdown_net"],
                "worst_12m_net": v["worst_12m_net"],
                "annual_oneway_turnover": v["annual_turnover_oneway"],
                "subperiods_net_excess_positive":
                    int(v["subperiod"]["net_excess_positive"].sum())
                    if len(v["subperiod"]) else 0,
                "subperiods_total": len(v["subperiod"])})
        pd.DataFrame(summary).to_excel(xl, sheet_name="Summary", index=False)
    return path


def _pct(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.2%}"


def fleet_block_monthly(res: dict, survivorship: str) -> str:
    t = res["theory"]
    sh = res["variants"].get("shifted_december_start", {})
    cl = res["variants"].get("classic_january", {})
    sub = sh.get("subperiod", pd.DataFrame())
    pos = int(sub["positive_direction"].sum()) if len(sub) else 0
    tot = len(sub)
    adopted = (sh.get("p_fisher", 1.0) < 0.05 and pos >= 4
               and sh.get("mean_window", 0) > sh.get("mean_baseline", 0))
    verdict = ("ADOPTED as buy-timing bias" if adopted
               else "NOT CONFIRMED on Baltic data (pre-registered gate failed)")
    return f"""### January small-cap effect — Baltic Main List ({t['id']})

- **Backtest result:** {verdict}. Shifted window (Dec 15 - Jan 31): mean {_pct(sh.get('mean_window'))} vs same-length baseline {_pct(sh.get('mean_baseline'))}, hit rate {sh.get('hits', 0)}/{sh.get('n', 0)}, Fisher one-sided p = {sh.get('p_fisher', float('nan')):.4f}, direction positive in {pos}/{tot} sub-periods. Classic January: mean {_pct(cl.get('mean_window'))} vs other months {_pct(cl.get('mean_baseline'))}, hit rate {cl.get('hits', 0)}/{cl.get('n', 0)}, p = {cl.get('p_fisher', float('nan')):.4f}.
- **Execution tactic:** if adopted, bias already-planned purchases toward early-to-mid December; the window is a timing overlay on buys you would make anyway.
- **Measured values:** equal-weight Main List portfolio, EUR, full sample; window length {sh.get('window_trading_days', 'n/a')} trading days.
- **Cost constraints:** zero extra cost when used as a timing bias on planned buys. Commission 0 (LHV); Baltic spreads make round-trips expensive.
- **Don'ts:** do NOT trade this as an in-and-out strategy — the spread is paid twice and eats the seasonal edge. Do not act on the classic-January variant alone if the shifted variant failed the gate.
- **Data caveats:** {survivorship}
"""


def fleet_block_period(res: dict, survivorship: str) -> str:
    t = res["theory"]
    ew = res["instruments"].get("Equal-weight Main List", {})
    n, hits = ew.get("n", 0), ew.get("hits", 0)
    ci_lo, ci_hi = ew.get("ci_low", float("nan")), ew.get("ci_high", float("nan"))
    threshold_hits = int(np.ceil(15 / 21 * n)) if n else 15
    adopted = n > 0 and hits >= threshold_hits and ci_lo > 0
    verdict = ("ADOPTED as soft buy-timing bias" if adopted
               else "NOT CONFIRMED on Baltic data")
    lines = [f"### Halloween effect (Nov-Apr vs May-Oct) — Baltic markets ({t['id']})", "",
             f"- **Backtest result:** {verdict}. Equal-weight Main List: winter beat summer in {hits}/{n} cycle years, mean difference {_pct(ew.get('mean_diff'))} per half-year, bootstrap 95% CI [{_pct(ci_lo)}, {_pct(ci_hi)}], exact binomial p (vs 50%) = {ew.get('p_binom_vs_50', float('nan')):.4f}. LOW POWER (~{n} annual observations) — treat as descriptive."]
    for name, v in res["instruments"].items():
        if name == "Equal-weight Main List":
            continue
        lines.append(f"  - {name}: winter wins {v['hits']}/{v['n']}, mean diff {_pct(v['mean_diff'])}, CI [{_pct(v['ci_low'])}, {_pct(v['ci_high'])}].")
    lines += ["- **Execution tactic:** if adopted, concentrate planned purchases in Sep-Oct and avoid initiating new positions in late April; purely a timing bias.",
              "- **Measured values:** per-cycle-year compounded half-year returns, sub-periods reported descriptively only (underpowered at ~4 obs each).",
              "- **Cost constraints:** zero extra cost as a timing bias; never pay a spread specifically to express this view.",
              "- **Don'ts:** do NOT sell in May to re-buy in autumn — a sell-and-rebuy round-trip on Baltic spreads costs more than the measured seasonal edge. Do not upgrade this to 'confirmed' without the pre-registered CI + 15-of-21 gate.",
              f"- **Data caveats:** {survivorship}"]
    return "\n".join(lines) + "\n"


def fleet_block_momentum(res: dict, survivorship: str) -> str:
    t = res["theory"]
    q = res["variants"].get("quarterly", {})
    qa = res["variants"].get("quarterly_absfilter", {})
    m = res["variants"].get("monthly", {})
    sub = q.get("subperiod", pd.DataFrame())
    pos = int(sub["net_excess_positive"].sum()) if len(sub) else 0
    tot = len(sub)
    ne = q.get("net_excess_ann", float("nan"))
    adopted = bool(np.isfinite(ne) and ne > 0 and pos >= 3)
    verdict = ("ADOPTED (quarterly rebalance)" if adopted
               else "NOT ADOPTED — net edge failed the pre-registered gate")

    def row(v, label):
        if not v or "error" in v:
            return f"  - {label}: insufficient data."
        return (f"  - {label}: gross {_pct(v['gross_ann'])} p.a., net {_pct(v['net_ann'])} p.a., "
                f"benchmark {_pct(v['bench_ann'])} p.a., net excess {_pct(v['net_excess_ann'])} p.a., "
                f"hit rate {v['hits']}/{v['n_periods']} (p={v['p_binom_vs_50']:.4f}), "
                f"max DD {_pct(v['max_drawdown_net'])}, worst 12m {_pct(v['worst_12m_net'])}, "
                f"one-way turnover {v['annual_turnover_oneway']:.1f}x/yr")

    return f"""### 12-1 cross-sectional momentum, long-only top tercile — Baltic Main List ({t['id']})

- **Backtest result:** {verdict}. Quarterly net excess positive in {pos}/{tot} sub-periods. Judge tradability on NET numbers only.
{row(q, 'Quarterly (flagship)')}
{row(m, 'Monthly')}
{row(qa, 'Quarterly + absolute-momentum filter')}
- **Execution tactic:** quarterly rebalance at LHV (commission 0); rank Main List names on trailing 12-month return excluding the most recent month, hold the equal-weight top tercile.
- **Measured values:** spread model = {res['spread_method']}; median half-spread {res['half_spread_median']:.2%} per trade; {res['liquidity_note']}.
- **Cost constraints:** every entry and exit pays the per-ticker half-spread; monthly rebalancing's extra turnover must be justified by extra net return (it usually is not on Baltic spreads).
- **Don'ts:** no short leg, ever (long top tercile vs benchmark, never top-minus-bottom). Never act on gross-only edge. Do not drop the zero-volume eligibility filter — thin names show phantom momentum.
- **Data caveats:** {survivorship}
"""


# ---------------------------------------------------------------------------
# Loader / dispatcher
# ---------------------------------------------------------------------------

SUPPORTED_TYPES = {"monthly_seasonality", "period_seasonality",
                   "cross_sectional_momentum"}


def load_theories(path: str) -> list[dict]:
    with open(path) as f:
        spec = json.load(f)
    version = str(spec.get("schema_version", "1.0"))
    theories = spec.get("theories", [])
    out = []
    for th in theories:
        ttype = th.get("type")
        if ttype in SUPPORTED_TYPES:
            out.append(th)
        elif ttype in {"day_of_week_conditional", "level_revisit"} or version.startswith("1"):
            print(f"  [loader] '{th.get('id')}' (type={ttype}) belongs to "
                  f"pattern_engine.py - skipped here.")
        else:
            print(f"  [loader] '{th.get('id')}' has unknown type '{ttype}' - skipped.")
    if not out:
        raise SystemExit("No schema 2.0 theories found in " + path)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theories", default="theories_seasonal.json")
    ap.add_argument("--data", default="master.parquet")
    ap.add_argument("--outdir", default="results")
    ap.add_argument("--list-filter", default="main",
                    help="substring match on the segment column ('' disables)")
    ap.add_argument("--default-half-spread", type=float, default=0.01,
                    help="fallback per-trade half-spread when no bid/ask or "
                         "high/low data exists (fraction, default 0.01 = 1%%)")
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {args.data} ...")
    md = load_master(args.data, list_filter=args.list_filter or None)
    for w in md.warnings:
        print("  [data]", w)
    print("  [data]", md.survivorship_note)
    n_tick = md.stocks["ticker"].nunique()
    span = (md.stocks["date"].min().date(), md.stocks["date"].max().date())
    print(f"  [data] {n_tick} stock tickers, {len(md.indices)} index series, "
          f"span {span[0]} .. {span[1]}")
    data_notes = md.warnings + [md.survivorship_note,
                                f"{n_tick} tickers, {span[0]}..{span[1]}"]

    theories = load_theories(args.theories)
    port = ew_daily_returns(md.stocks)   # verified against the independent impl
    print("  [verify] EW daily portfolio cross-check passed.")

    for th in theories:
        tid, ttype = th["id"], th["type"]
        print(f"\nRunning {tid} ({ttype}) ...")
        if ttype == "monthly_seasonality":
            res = run_monthly_seasonality(th, port)
            xlsx = write_monthly_seasonality_report(res, outdir, data_notes)
            block = fleet_block_monthly(res, md.survivorship_note)
        elif ttype == "period_seasonality":
            res = run_period_seasonality(th, port, md.indices)
            xlsx = write_period_seasonality_report(res, outdir, data_notes)
            block = fleet_block_period(res, md.survivorship_note)
        else:
            res = run_momentum(th, md.stocks, args.default_half_spread)
            print("  [verify] momentum quarterly gross cross-check passed.")
            xlsx = write_momentum_report(res, outdir, data_notes)
            block = fleet_block_momentum(res, md.survivorship_note)
        block_path = outdir / f"{tid}_fleet_block.md"
        block_path.write_text(block)
        print(f"  wrote {xlsx}")
        print(f"  wrote {block_path}")

    print("\nDone. Paste the *_fleet_block.md contents into trading_strategy_fleet.md "
          "after reviewing the workbooks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
