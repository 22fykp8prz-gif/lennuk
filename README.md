# lennuk — CEE/Baltic power-engineering thesis harvester

Builds a searchable dataset of bachelor's/master's/doctoral theses in
electrical power and energy engineering, defended 2021–2026, across
institutions in Estonia, Latvia, Lithuania, Poland, Czechia, Slovakia,
Slovenia, Romania, Bulgaria and Türkiye. Purpose: talent scouting and
research-partner mapping (grid-connected storage, market modelling,
frequency reserves, grid connection, renewables integration).

## Status

**Phase 0 pipeline is built and tested; the live pilot harvest is blocked on
network egress policy.** This environment's egress proxy denies CONNECT to
every harvest host (default-deny allowlist). The Phase 0 run in
`output/phase0/` therefore contains **zero records and 19 logged source
failures** — see `output/phase0/harvest_log.csv` and `coverage_report.md`.
Zero rows means *unreachable sources*, not *no theses*. Nothing is ever
fabricated to fill a gap.

### Egress allowlist needed for a live run

| Phase | Hosts |
|---|---|
| 0 (pilot) | `api.openaire.eu`, `digikogu.taltech.ee`, `delibra.bg.polsl.pl`, `tez.yok.gov.tr` |
| 1 | + `dspace.ut.ee`, `ortus.rtu.lv`, `repo.pw.edu.pl`, `repozytorium.agh.edu.pl`, `mostwiedzy.pl`, `dspace.cvut.cz`, `dspace.vut.cz`, `dspace.vsb.cz`, `dspace5.zcu.cz`, `repozitorij.uni-lj.si`, `dk.um.si`, `dirros.openscience.si` |
| 2 | + `elaba.lvb.lt`, `theses.cz`, `crzp.cvtisr.sk` |
| optional | `zenodo.org` (full OpenAIRE Graph dump alternative to the API) |

## Architecture

Four tiers, run in order (see the brief for rationale):

1. **`harvester/tier1_openaire.py`** — OpenAIRE Graph API v2, queries
   partitioned institution × year so no partition nears the 10k paging cap
   (`numFound` asserted, truncation logged). Raw type strings kept in
   `type_raw`; normalisation happens post-parse, not at query time.
2. **`harvester/tier2_oaipmh.py`** — direct OAI-PMH per repository.
   Endpoints are *discovered* (conventional DSpace/dLibra/EPrints paths +
   `?verb=Identify`), never hardcoded. Full `ListSets` output is persisted
   for human review; `ListRecords` follows `resumptionToken` to exhaustion.
3. **`harvester/tier3_yok.py`** — YÖK Ulusal Tez Merkezi (TR), Playwright
   browser module. Slowest and most fragile; own log (`yok_log.csv`),
   conservative pacing, raw HTML cached before parsing. Selectors must be
   verified against the live site on the first networked run.
4. **`harvester/gaps.py`** — `gaps.csv` for institutions with no
   machine-readable route (Romania/Bulgaria mostly): what was tried, what
   exists, suggested contact route.

Shared plumbing:

- `harvester/http.py` — polite client: ≤1 req/s per host, exponential
  backoff on 429/5xx (2/4/8/16s), descriptive User-Agent (set
  `HARVESTER_CONTACT=you@example.org`), raw responses cached to `data/raw/`
  before parsing so runs are idempotent and resumable.
- `harvester/normalize.py` — degree-level normalisation across 10 languages;
  unmatched → `unknown`, never guessed; raw string kept in `level_raw`.
  Encodes the traps (PL `praca inżynierska` = first cycle, CZ/SK
  `diplomová práce` = master's, SI `diplomsko delo` ambiguous by era).
- `harvester/scoring.py` — two independent relevance signals, both stored,
  no harvest-time thresholding: multilingual domain terms (`domain_flags`)
  and national-context flags (`national_flags`, canonical names with
  inflected surface forms). `relevance_score = |domain| + 2·|national|`.
- `harvester/schema.py` / `outputs.py` — one row per thesis, verbatim
  metadata (diacritics intact, no transliteration/translation), stable id =
  hash(source + native identifier); cross-source dedup prefers
  OAI-PMH > YÖK > OpenAIRE and fills gaps without overwriting.
- `harvester/log.py` / `report.py` — `harvest_log.csv` (one row per source
  attempt; failures are explicit, never silent zeros) and
  `coverage_report.md` (per-institution record counts, year span, share
  with abstract/advisor/full text).

## Running

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export HARVESTER_CONTACT="you@example.org"   # goes into the User-Agent

python -m harvester run --phase 0    # pilot: TalTech, Silesian UT, İTÜ
python -m harvester run --phase 1    # all tier-A, tiers 1+2
```

Outputs land in `output/phaseN/`: `theses.parquet`, `theses.csv`,
`harvest_log.csv`, `gaps.csv`, `coverage_report.md`, `sample_rows.csv`
(top 50 by relevance), plus `yok_log.csv` when the YÖK module ran.
Raw responses cache under `data/` (gitignored); `--offline` replays a
previous run purely from cache.

Configuration lives in `institutions.csv` (tiers, repository URLs, OpenAIRE
org names, YÖK university names, pilot flags). No credentials in code.

Tests: `python -m pytest` — parser tests run against synthetic fixtures in
`tests/fixtures/` (clearly marked; never mixed into harvested data).

## Phasing

- **Phase 0** — pilot: TalTech (EE), Silesian UT (PL), İTÜ (TR via YÖK).
  Full pipeline end to end, then stop for review of the coverage report.
- **Phase 1** — all tier-A institutions, Tiers 1+2.
- **Phase 2** — national systems (eLABa, Theses.cz, CRZP), YÖK last.
- **Phase 3** — tier-B/C institutions + gap report.

## Personal data

Records name real individuals. Everything harvested is already published by
the institutions, but the dataset falls under GDPR the moment it is used for
recruitment: keep it internal, the `source`/`url_landing` columns document
provenance per record, and it must not be merged with scraped social
profiles as part of this job.
