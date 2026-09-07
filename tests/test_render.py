"""Playwright rendering tests against a local JS-only fixture site.

Skipped automatically when Playwright (or its Chromium) is not available.
"""

import http.server
import threading
from pathlib import Path

import pytest

from gas_plant_scraper import browser
from gas_plant_scraper.catalog import Catalog
from gas_plant_scraper.crawler import SourceConfig, SourceCrawler
from gas_plant_scraper.fetch import Fetcher

pytestmark = pytest.mark.skipif(
    not browser.available(), reason="playwright not installed"
)

# The page body is empty until JavaScript runs — exactly how SPA portals
# (PLANK, ylupa.avi.fi) behave for a plain HTTP client.
SPA_INDEX = """<!doctype html>
<html><head><meta charset="utf-8"><title>SPA</title></head>
<body><div id="app"></div>
<script>
document.getElementById('app').innerHTML =
  '<h1>Gaasiturbiin elektrijaam 45 MW</h1>' +
  '<ul>' +
  '<li><a href="/docs/asendiplaan.pdf">Asendiplaan</a></li>' +
  '<li><a href="/docs/seletuskiri.pdf">Seletuskiri</a></li>' +
  '<li><a href="/#/projekt/2">Teine gaasijaama projekt</a></li>' +
  '</ul>';
</script>
</body></html>
"""


@pytest.fixture()
def renderer():
    try:
        r = browser.Renderer(delay_seconds=0.0, settle_ms=100)
        with r:
            yield r
    except Exception as exc:  # Chromium missing etc.
        pytest.skip(f"cannot launch Chromium: {exc}")


@pytest.fixture()
def spa_server(tmp_path):
    site = tmp_path / "site"
    (site / "docs").mkdir(parents=True)
    (site / "index.html").write_text(SPA_INDEX, encoding="utf-8")
    (site / "docs" / "asendiplaan.pdf").write_bytes(b"%PDF dummy")
    (site / "docs" / "seletuskiri.pdf").write_bytes(b"%PDF dummy")

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(site), **kw
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_renderer_executes_javascript(renderer, spa_server):
    html = renderer.get_html(f"{spa_server}/index.html")
    assert html is not None
    assert "Asendiplaan" in html  # present only after JS ran


def test_spa_crawl_finds_js_injected_documents(renderer, spa_server, tmp_path):
    source = SourceConfig(
        id="spa_src",
        country="EE",
        name="SPA test",
        languages=["et"],
        seeds=[f"{spa_server}/index.html"],
        allowed_domains=["127.0.0.1"],
        max_depth=1,
        max_pages=10,
        render=True,
    )
    catalog = Catalog(tmp_path / "c.sqlite")
    fetcher = Fetcher(delay_seconds=0.0, respect_robots=False)
    crawler = SourceCrawler(
        source, fetcher, catalog, tmp_path / "data",
        download=False, renderer=renderer,
    )
    stats = crawler.run()
    urls = {r["url"] for r in catalog.rows()}

    assert any(u.endswith("asendiplaan.pdf") for u in urls)
    assert any(u.endswith("seletuskiri.pdf") for u in urls)
    assert stats.pages_fetched >= 1
    catalog.close()


def test_spa_crawl_without_renderer_finds_nothing(spa_server, tmp_path):
    """Control: the same SPA over plain HTTP yields no documents."""
    source = SourceConfig(
        id="spa_src2",
        country="EE",
        name="SPA test",
        languages=["et"],
        seeds=[f"{spa_server}/index.html"],
        allowed_domains=["127.0.0.1"],
        max_depth=1,
        max_pages=10,
        render=True,  # render requested, but no renderer supplied
    )
    catalog = Catalog(tmp_path / "c2.sqlite")
    fetcher = Fetcher(delay_seconds=0.0, respect_robots=False)
    crawler = SourceCrawler(
        source, fetcher, catalog, tmp_path / "data2",
        download=False, renderer=None,
    )
    crawler.run()
    assert catalog.rows() == []
    catalog.close()


def test_hash_fragment_kept_for_rendered_sources(renderer, spa_server, tmp_path):
    source = SourceConfig(
        id="spa_src3",
        country="EE",
        name="SPA test",
        languages=["et"],
        seeds=[f"{spa_server}/index.html#/planning/search?text=gaasiturbiin"],
        allowed_domains=["127.0.0.1"],
        max_depth=0,
        max_pages=5,
        render=True,
    )
    catalog = Catalog(tmp_path / "c3.sqlite")
    fetcher = Fetcher(delay_seconds=0.0, respect_robots=False)
    crawler = SourceCrawler(
        source, fetcher, catalog, tmp_path / "data3",
        download=False, renderer=renderer,
    )
    # _normalize must keep the fragment (SPA route), unlike the HTTP path.
    normalized = crawler._normalize(source.seeds[0])
    assert "#/planning/search" in normalized
    stats = crawler.run()
    assert stats.pages_fetched == 1
    catalog.close()
