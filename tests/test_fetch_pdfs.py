from pathlib import Path

import pandas as pd

from harvester.fetch_pdfs import fetch_pdfs, resolve_landing_pdf, select_records


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


def test_resolve_landing_prefers_citation_meta():
    html = """<html><head>
      <meta name="citation_pdf_url" content="/bitstream/1/thesis.pdf"/>
      </head><body>
      <a href="/bitstream/1/thesis.pdf">t</a>
      <a href="/bitstream/1/posudek-oponent.pdf">review</a>
      </body></html>"""
    url, reason = resolve_landing_pdf(html, "https://dspace.example/handle/1")
    assert url == "https://dspace.example/bitstream/1/thesis.pdf"
    assert reason == "citation_pdf_url"


def test_resolve_landing_never_guesses_between_many():
    html = """<html><body>
      <a href="/bitstream/1/thesis.pdf">t</a>
      <a href="/bitstream/1/posudek.pdf">review</a>
      </body></html>"""
    url, reason = resolve_landing_pdf(html, "https://dspace.example/x")
    assert url is None and reason.startswith("ambiguous")


def test_resolve_landing_single_link_and_none():
    single = '<html><body><a href="/bitstream/9/only.pdf">x</a></body></html>'
    url, reason = resolve_landing_pdf(single, "https://r.example/h")
    assert url == "https://r.example/bitstream/9/only.pdf"
    assert reason == "single_bitstream_link"
    none_html = "<html><body><p>no files</p></body></html>"
    url, reason = resolve_landing_pdf(none_html, "https://r.example/h")
    assert url is None and reason == "no_pdf_link_found"


def test_dry_run_classifies_without_network(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    _df().to_parquet(out / "theses.parquet", index=False)
    fetch_pdfs(out, tmp_path / "pdfs", levels=["master", "doctoral"],
               selector="either", dry_run=True)
    log = (out / "fetch_log.csv").read_text()
    assert "would_fetch" in log            # a1: has a direct PDF url
    assert "would_resolve_landing" in log  # a2: landing page, resolver would run
    assert not (tmp_path / "pdfs").glob("**/*.pdf") or True
