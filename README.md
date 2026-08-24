# lennuk
Lennuki oma

## Seasonal & momentum theory engine (schema 2.0)

Backtest engine for the three theories in `theories_seasonal.json`
(January small-cap effect, Halloween effect, 12-1 long-only momentum) on the
Baltic Main List universe. Spec: `docs_seasonal_momentum_handoff.md`.

### Files

| File | Purpose |
|---|---|
| `seasonal_engine.py` | Schema 2.0 loader + engines for `monthly_seasonality`, `period_seasonality`, `cross_sectional_momentum`; writes one Excel workbook and one fleet-ruleset block per theory. |
| `verify_seasonal.py` | Independent, deliberately simple pandas implementations; every portfolio return series is cross-checked against these before results are accepted (run aborts on mismatch). |
| `theories_seasonal.json` | Theory specs, schema_version 2.0. Theories with pattern-engine types (day-of-week) are skipped with a note, so a merged theories file can be passed too. |
| `tests/smoke_test.py` | End-to-end run on synthetic data with a planted January edge; asserts outputs, cross-checks, universe filtering and survivorship detection. |

### Usage

Run in the directory that holds `master.parquet` (202 tickers, 2005-2026):

```bash
pip install pandas numpy pyarrow openpyxl
python seasonal_engine.py --theories theories_seasonal.json \
                          --data master.parquet --outdir results
```

Outputs per theory in `results/`:

* `<theory_id>.xlsx` — Parameters, per-year tables, five-sub-period tables, gross/net Summary.
* `<theory_id>_fleet_block.md` — paste-ready results block for `trading_strategy_fleet.md`, with the ADOPTED / NOT CONFIRMED verdict evaluated automatically against the pre-registered decision thresholds from the handoff brief.

### Data expectations for `master.parquet`

Long format with columns (several spellings recognized, case-insensitive):
`date`, `ticker`, `close` required; `volume`, `bid`/`ask`, `high`/`low`,
`segment` optional. A wide frame (date index, ticker columns) also works, with
liquidity filter and measured spreads disabled.

* **Universe:** filtered to rows whose segment column matches `--list-filter`
  (default `main`); if no segment column exists, the file is assumed to already
  be Main List only (a warning is printed).
* **Indices:** tickers starting with `OMXT`/`OMXR`/`OMXV` are treated as index
  series and used by the Halloween theory (plus the equal-weight portfolio).
* **Spread model:** median quoted half-spread if bid/ask exist, else
  Corwin-Schultz high-low estimator, else `--default-half-spread` (1% default),
  clipped to [0.05%, 5%]; applied on every entry and exit. Commission 0 (LHV).
* **Survivorship:** if every ticker trades to the end of the sample, the run
  prints a warning and stamps it into the workbooks and fleet blocks —
  momentum results are then an upper bound.

### Testing

```bash
python tests/smoke_test.py
```
