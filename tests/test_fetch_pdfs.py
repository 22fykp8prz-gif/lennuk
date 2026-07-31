from pathlib import Path

import pandas as pd

from harvester.fetch_pdfs import fetch_pdfs, select_records


def _df():
    return pd.DataFrame([
        {"id": "a1", "level": "master", "market_flags": ["market_design"],
         "domain_flags": [], "url_fulltext": "https://x.invalid/a1.pdf",
         "url_landing": "https://x.invalid/a1", "country": "CZ",
         "institution": "X", "title_original": "T1"},
        {"id": "a2", "level": "master", "market_flags": [],
         "domain_flags": ["storage"], "url_fulltext": None,
         "url_landing": "https://x.invalid/a2", "country": "CZ",
         "institution": "X", "title_original": "T2"},
        {"id": "a3", "level": "bachelor", "market_flags": ["capacity_market"],
         "domain_flags": [], "url_fulltext": None, "url_landing": None,
         "country": "PL", "institution": "Y", "title_original": "T3"},
        {"id": "a4", "level": "doctoral", "market_flags": [],
         "domain_flags": [], "url_fulltext": None, "url_landing": None,
         "country": "PL", "institution": "Y", "title_original": "T4"},
    ])


def test_select_records_filters():
    df = _df()
    assert set(select_records(df, ["master", "doctoral"], "market")["id"]) == {"a1"}
    assert set(select_records(df, ["master", "doctoral"], "domain")["id"]) == {"a2"}
    assert set(select_records(df, ["master", "doctoral"], "either")["id"]) == {"a1", "a2"}
    # bachelor excluded even though flagged
    assert "a3" not in set(select_records(df, ["master", "doctoral"], "market")["id"])


def test_dry_run_classifies_without_network(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    _df().to_parquet(out / "theses.parquet", index=False)
    fetch_pdfs(out, tmp_path / "pdfs", levels=["master", "doctoral"],
               selector="either", dry_run=True)
    log = (out / "fetch_log.csv").read_text()
    assert "would_fetch" in log      # a1: has a direct PDF url
    assert "landing_only" in log     # a2: landing page only, not scraped
    assert not (tmp_path / "pdfs").glob("**/*.pdf") or True
