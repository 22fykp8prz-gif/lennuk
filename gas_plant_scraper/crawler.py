"""Generic keyword-driven crawler for planning/EIA portals.

Strategy per source (configured in config/sources.yaml):
1. Start from seed URLs and, when a ``search_url`` template exists, from
   search result pages for each configured keyword.
2. Follow in-domain links whose anchor text or URL mentions gas-plant terms,
   up to ``max_depth``.
3. Download linked document files (PDF/DWG/DOCX/...), classify them
   (drawing / description / safety / infrastructure / permit), extract MW
   figures from surrounding text (and PDF contents when pypdf is available),
   and record everything in the catalog.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus, urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .catalog import Catalog
from .classify import (
    classify_doc_types,
    extract_mw_values,
    mw_bucket,
    relevance_score,
)
from .fetch import Fetcher
from .keywords import DOCUMENT_EXTENSIONS, SEARCH_TERMS

log = logging.getLogger(__name__)

try:  # optional dependency, used to read MW figures out of PDFs; a broken
    # install (e.g. missing cryptography backend raises a non-Exception
    # panic) must not kill the crawler
    from pypdf import PdfReader
except KeyboardInterrupt:  # pragma: no cover
    raise
except BaseException:  # pragma: no cover
    PdfReader = None


@dataclass
class SourceConfig:
    id: str
    country: str
    name: str
    languages: list[str]
    seeds: list[str]
    allowed_domains: list[str]
    search_url: str | None = None
    max_depth: int = 2
    max_pages: int = 200
    render: bool = False  # render pages in headless Chromium (SPA portals)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "SourceConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class CrawlStats:
    pages_fetched: int = 0
    documents_found: int = 0
    documents_downloaded: int = 0
    errors: int = 0
    by_type: dict = field(default_factory=dict)


def _domain_allowed(url: str, allowed: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowed)


def _is_document_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in DOCUMENT_EXTENSIONS)


def _safe_filename(url: str, max_len: int = 120) -> str:
    name = Path(urlparse(url).path).name or "document"
    name = re.sub(r"[^A-Za-z0-9._\-]+", "_", name)
    return name[-max_len:]


def _pdf_text(path: Path, max_pages: int = 30) -> str:
    if PdfReader is None or path.suffix.lower() != ".pdf":
        return ""
    try:
        reader = PdfReader(str(path))
        return " ".join(
            (page.extract_text() or "") for page in reader.pages[:max_pages]
        )
    except Exception as exc:  # damaged/encrypted PDFs are common in registries
        log.debug("pdf text extraction failed for %s: %s", path, exc)
        return ""


class SourceCrawler:
    def __init__(
        self,
        source: SourceConfig,
        fetcher: Fetcher,
        catalog: Catalog,
        out_dir: Path,
        max_docs: int | None = None,
        min_relevance: int = 1,
        download: bool = True,
        renderer=None,
    ):
        self.source = source
        self.fetcher = fetcher
        self.renderer = renderer if source.render else None
        self.catalog = catalog
        self.out_dir = out_dir / source.country / source.id
        self.max_docs = max_docs
        self.min_relevance = min_relevance
        self.download = download
        self.stats = CrawlStats()

    # ── entry points ─────────────────────────────────────────────────────
    def start_urls(self) -> list[str]:
        urls = list(self.source.seeds)
        if self.source.search_url:
            for lang in self.source.languages:
                for term in SEARCH_TERMS.get(lang, []):
                    urls.append(
                        self.source.search_url.format(query=quote_plus(term))
                    )
        return urls

    def _normalize(self, url: str) -> str:
        # SPA portals route via URL fragments (#/planning/search), so keep
        # fragments for rendered sources; strip them everywhere else.
        return url if self.renderer is not None else urldefrag(url)[0]

    def run(self) -> CrawlStats:
        queue: deque[tuple[str, int]] = deque(
            (url, 0) for url in self.start_urls()
        )
        seen: set[str] = set()
        while queue and self.stats.pages_fetched < self.source.max_pages:
            if self.max_docs and self.stats.documents_found >= self.max_docs:
                break
            url, depth = queue.popleft()
            url = self._normalize(url)
            if url in seen or not _domain_allowed(url, self.source.allowed_domains):
                continue
            seen.add(url)
            self._visit(url, depth, queue, seen)
        return self.stats

    # ── page handling ────────────────────────────────────────────────────
    def _page_html(self, url: str) -> str | None:
        """Fetch page HTML: headless-browser render for SPA sources
        (falling back to plain HTTP), plain HTTP otherwise."""
        if self.renderer is not None:
            if not self.fetcher.allowed(url):
                log.info("robots.txt disallows %s", url)
                return None
            html = self.renderer.get_html(url)
            if html is not None:
                return html
            log.info("render failed, falling back to HTTP for %s", url)
        resp = self.fetcher.get(url)
        if resp is None:
            return None
        try:
            content_type = resp.headers.get("Content-Type", "")
            if "html" not in content_type:
                return ""
            if "charset" not in content_type.lower():
                # Requests defaults to ISO-8859-1 when the header is silent,
                # which garbles accented text; sniff the real encoding.
                resp.encoding = resp.apparent_encoding
            return resp.text
        finally:
            resp.close()

    def _visit(
        self, url: str, depth: int, queue: deque, seen: set[str]
    ) -> None:
        html = self._page_html(url)
        if html is None:
            self.stats.errors += 1
            return
        if not html:
            return  # non-HTML resource
        self.stats.pages_fetched += 1
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(" ", strip=True)[:20000]
        page_relevant = relevance_score(page_text) >= self.min_relevance

        for anchor in soup.find_all("a", href=True):
            link = self._normalize(urljoin(url, anchor["href"]))
            if link in seen:
                continue
            text = anchor.get_text(" ", strip=True)
            # Context: the anchor's own text plus its parent block, so that
            # "Lisa 3" next to "asendiplaan" still classifies correctly.
            parent = anchor.find_parent(["li", "tr", "p", "div"])
            context = f"{text} {parent.get_text(' ', strip=True)[:500]}" if parent else text

            if _is_document_url(link):
                if page_relevant or relevance_score(context, link) >= self.min_relevance:
                    seen.add(link)
                    self._handle_document(link, text or context[:150], url, context, page_text)
            elif depth < self.source.max_depth:
                if relevance_score(context, link) >= self.min_relevance:
                    queue.append((link, depth + 1))

    def _handle_document(
        self, url: str, title: str, page_url: str, context: str, page_text: str
    ) -> None:
        if self.catalog.has(url):
            return
        if self.max_docs and self.stats.documents_found >= self.max_docs:
            return
        self.stats.documents_found += 1

        doc_types = classify_doc_types(context, url)
        mw_values = extract_mw_values(f"{context} {page_text[:5000]}")
        local_path: str | None = None
        size: int | None = None

        # Documents hosted off-domain (e.g. CDNs) are still downloaded, but
        # only over HTTPS.
        off_domain_http = (
            not _domain_allowed(url, self.source.allowed_domains)
            and not url.startswith("https://")
        )
        if self.download and not off_domain_http:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            dest = self.out_dir / f"{self.stats.documents_found:04d}_{_safe_filename(url)}"
            size = self.fetcher.download(url, str(dest))
            if size is not None:
                local_path = str(dest)
                self.stats.documents_downloaded += 1
                pdf_text = _pdf_text(dest)
                if pdf_text:
                    mw_values = mw_values or extract_mw_values(pdf_text)
                    doc_types = doc_types or classify_doc_types(pdf_text[:8000], url)
            else:
                self.stats.errors += 1

        for doc_type in doc_types or ["unclassified"]:
            self.stats.by_type[doc_type] = self.stats.by_type.get(doc_type, 0) + 1

        self.catalog.add(
            url=url,
            source_id=self.source.id,
            country=self.source.country,
            title=title,
            page_url=page_url,
            doc_types=doc_types,
            mw_values=mw_values,
            mw_bucket=mw_bucket(mw_values),
            relevance=relevance_score(context, url),
            local_path=local_path,
            size_bytes=size,
        )
        log.info(
            "[%s] %s (%s) %s", self.source.id, title[:60],
            ",".join(doc_types) or "unclassified", url,
        )
