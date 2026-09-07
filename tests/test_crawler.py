"""Integration test: crawl a fixture site served from a local HTTP server."""

import http.server
import threading
from pathlib import Path

import pytest

from gas_plant_scraper.catalog import Catalog
from gas_plant_scraper.crawler import SourceConfig, SourceCrawler
from gas_plant_scraper.fetch import Fetcher

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fixture_server(tmp_path):
    # Build a small site: the project page plus dummy documents.
    site = tmp_path / "site"
    (site / "docs").mkdir(parents=True)
    (site / "muu").mkdir()
    (site / "projektid").mkdir()
    (site / "index.html").write_text(
        (FIXTURES / "project_page.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for name in ["seletuskiri.pdf", "asendiplaan.pdf", "lisa3.dwg",
                 "riskianalyys.pdf", "liitumine.pdf"]:
        (site / "docs" / name).write_bytes(b"%PDF-1.4 dummy 49,9 MW")
    (site / "muu" / "lasteaed.pdf").write_bytes(b"%PDF-1.4 dummy")
    (site / "projektid" / "teine-gaasijaam").mkdir()
    (site / "projektid" / "teine-gaasijaam" / "index.html").write_text(
        '<html><body><p>Gaasimootor 18 MW</p>'
        '<a href="/docs/asendiplaan.pdf">Asendiplaan</a></body></html>',
        encoding="utf-8",
    )

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(site), **kw
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_crawl_fixture_site(fixture_server, tmp_path):
    source = SourceConfig(
        id="test_src",
        country="EE",
        name="Test",
        languages=["et"],
        seeds=[f"{fixture_server}/index.html"],
        allowed_domains=["127.0.0.1"],
        max_depth=2,
        max_pages=20,
    )
    catalog = Catalog(tmp_path / "catalog.sqlite")
    fetcher = Fetcher(delay_seconds=0.0, respect_robots=False)
    crawler = SourceCrawler(
        source, fetcher, catalog, tmp_path / "data", download=True
    )
    stats = crawler.run()
    rows = catalog.rows()
    urls = {r["url"] for r in rows}

    # Relevant documents were found …
    assert any(u.endswith("seletuskiri.pdf") for u in urls)
    assert any(u.endswith("asendiplaan.pdf") for u in urls)
    assert any(u.endswith("lisa3.dwg") for u in urls)
    assert any(u.endswith("riskianalyys.pdf") for u in urls)

    # … and classified correctly.
    by_name = {r["url"].rsplit("/", 1)[-1]: r for r in rows}
    assert "drawing" in by_name["asendiplaan.pdf"]["doc_types"]
    assert "drawing" in by_name["lisa3.dwg"]["doc_types"]
    assert "safety" in by_name["riskianalyys.pdf"]["doc_types"]
    assert "description" in by_name["seletuskiri.pdf"]["doc_types"]
    assert "infrastructure" in by_name["liitumine.pdf"]["doc_types"]

    # MW figures on the page were picked up and bucketed.
    assert by_name["seletuskiri.pdf"]["mw_bucket"] == "<=50 MW"

    # Files were actually downloaded.
    assert stats.documents_downloaded >= 4
    downloaded = [r for r in rows if r["local_path"]]
    assert all(Path(r["local_path"]).exists() for r in downloaded)

    # The crawler followed the in-domain project link (depth 1).
    assert stats.pages_fetched >= 2

    catalog.close()


def test_catalog_dedup(tmp_path):
    catalog = Catalog(tmp_path / "c.sqlite")
    kwargs = dict(
        url="https://x.ee/a.pdf", source_id="s", country="EE", title="t",
        page_url="https://x.ee/", doc_types=["drawing"], mw_values=[10.0],
        mw_bucket="<=20 MW", relevance=2, local_path=None, size_bytes=None,
    )
    catalog.add(**kwargs)
    catalog.add(**kwargs)
    assert len(catalog.rows()) == 1
    assert catalog.has("https://x.ee/a.pdf")
    catalog.close()
