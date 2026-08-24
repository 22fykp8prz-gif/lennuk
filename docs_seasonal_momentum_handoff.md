# Handoff Brief: Seasonal & Momentum Theory Specs

**For:** Claude Code, local repo (nasdaq_baltic.py / consolidate_shares.py / pattern_engine.py / theories.json)
**Input:** `theories_seasonal.json` (schema_version 2.0)
**Data:** `master.parquet` (202 tickers, 2005-2026)

## Why a schema extension

The existing `pattern_engine.py` computes hit rates for day-of-week conditional level-revisit patterns. The three new theories need return-based statistics, so the engine requires three new theory types:

1. `monthly_seasonality` — calendar-window portfolio returns vs same-length baseline windows (January effect).
2. `period_seasonality` — two fixed half-year windows compared per year (Halloween effect).
3. `cross_sectional_momentum` — ranked portfolio construction with rebalancing, turnover, and spread costs (12-1 momentum).

Recommended structure: keep `pattern_engine.py` untouched for Patterns 1-2; add `seasonal_engine.py` that dispatches on the `type` field and shares the existing Fisher's exact (log-gamma) implementation for all hit-rate metrics.

## Non-negotiable methodology rules (carried over from fleet standards)

- Full 2005-2026 period first; the 3-week pilot lesson applies — no conclusions from short samples.
- Five-sub-period stability check wherever sample size permits; where underpowered (Halloween, ~21 annual obs), report descriptively with bootstrap CIs and say so explicitly.
- Report gross AND net returns. Net = after per-trade half-spread on every entry and exit. Commission 0 (LHV).
- Long-only throughout. No short leg anywhere, including in momentum (top tercile long vs benchmark, never top-minus-bottom).
- Survivorship: use all tickers present in master.parquet including delisted ones; flag if the parquet only contains currently listed names, because momentum results are meaningfully inflated by survivorship bias.
- Independent verification standard: cross-check portfolio return series with a second, simple pandas implementation before accepting results.

## Expected deliverables from the Claude Code run

1. `seasonal_engine.py` + updated loader accepting schema 2.0.
2. One Excel per theory (same layout as the 20-year backtest workbooks): per-year table, sub-period table, gross/net summary, parameter sheet.
3. A short results block per theory in fleet ruleset format (backtest result, execution tactic, measured values, cost constraints, explicit don'ts) — English, paste-ready for `trading_strategy_fleet.md`.

## Decision thresholds (pre-registered, to avoid post-hoc rationalization)

- **January effect:** adopt as buy-timing bias if the shifted (Dec 15) variant shows positive edge significant at p < 0.05 AND direction consistent in ≥4 of 5 sub-periods.
- **Halloween:** adopt as soft timing bias only if winter > summer in ≥15 of ~21 years AND bootstrap CI of the mean difference excludes zero. Otherwise file as "not confirmed on Baltic data".
- **Momentum 12-1:** adopt only if NET annualized excess return of the quarterly variant is positive across the full period AND in ≥3 of 5 sub-periods. Gross-only edge = not tradable, same verdict as Patterns 1-2 standalone use.
