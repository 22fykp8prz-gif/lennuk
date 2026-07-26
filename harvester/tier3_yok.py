"""Tier 3 — YÖK Ulusal Tez Merkezi (tez.yok.gov.tr), browser-driven.

No open API exists. The Detaylı Tarama form filters by university and year
and returns author, title, advisor, university, year, thesis type. Master's
and doctoral only — bachelor's theses are not in the system.

This is the slowest and most fragile part of the pipeline and is treated as
its own module with its own log (yok_log.csv). Conservative pacing: one
university at a time, multi-second waits between actions, raw HTML of every
result page saved to disk before parsing.

IMPORTANT: the selectors below follow the site's structure as last known and
MUST be verified against the live site on the first networked run — the
module fails loudly (logged failure, zero rows) rather than guessing.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .config import YEAR_FROM, YEAR_TO, Institution, USER_AGENT
from .log import HarvestLog
from .normalize import normalize_level
from .schema import new_record
from .scoring import apply_scoring

YOK_BASE = "https://tez.yok.gov.tr/UlusalTezMerkezi/"
SEARCH_URL = YOK_BASE + "tarama.jsp"

ACTION_PAUSE = 3.0  # seconds between page interactions — deliberately slow
DEPARTMENT_FILTERS = ["Elektrik-Elektronik Mühendisliği", "Enerji Sistemleri Mühendisliği"]


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def parse_results_html(html: str, inst: Institution, year: int) -> list[dict]:
    """Parse a results-table page into schema records.

    The results grid columns are: Tez No | Yazar | Yıl | Tez Adı (Orijinal/Çeviri)
    | Tez Türü | Konu. Advisor requires opening the record detail; when the
    detail was not fetched the advisor field stays empty rather than guessed.
    """
    from lxml import html as lhtml

    doc = lhtml.fromstring(html)
    records: list[dict] = []
    for row in doc.xpath("//table[@id='divResults']//tr[td] | //table[contains(@class,'GridView')]//tr[td]"):
        cells = [_clean(c.text_content()) for c in row.xpath("./td")]
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        tez_no, author, row_year, title_cell, tez_turu = cells[0], cells[1], cells[2], cells[3], cells[4]
        # Title cell holds original and translated title separated by a line break.
        title_parts = [
            _clean(p) for p in row.xpath("./td[4]//text()") if _clean(p)
        ] or [title_cell]
        rec = new_record(
            source="yok",
            native_id=tez_no,
            title_original=title_parts[0] or None,
            title_en=title_parts[1] if len(title_parts) > 1 else None,
            authors=[author] if author else [],
            year=int(row_year) if row_year.isdigit() else year,
            level=normalize_level(tez_turu),
            level_raw=tez_turu or None,
            type_raw=tez_turu or None,
            institution=inst.institution_en,
            country="TR",
            language="tr",
            url_landing=f"{YOK_BASE}tezSorguSonucYeni.jsp?tezNo={tez_no}",
        )
        records.append(apply_scoring(rec))
    return records


def harvest_institution(
    inst: Institution,
    log: HarvestLog,
    raw_dir: Path,
    year_from: int = YEAR_FROM,
    year_to: int = YEAR_TO,
    headless: bool = True,
) -> list[dict]:
    """Drive the Detaylı Tarama form for one university, one year at a time."""
    if not inst.yok_university_name:
        log.add("yok", SEARCH_URL, "skipped", institution=inst.institution_en,
                note="no YÖK university name configured")
        return []

    raw_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        log.add("yok", SEARCH_URL, "failed", institution=inst.institution_en,
                error=f"playwright not installed: {e}")
        return []

    # Managed environments pre-install a shared Chromium; use it when the
    # Playwright-pinned build is absent instead of downloading a browser.
    import os
    exe = None
    for candidate in ("/opt/pw-browsers/chromium",):
        if os.path.exists(candidate):
            exe = candidate
            break

    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(headless=headless)
            except Exception:
                if exe is None:
                    raise
                browser = pw.chromium.launch(headless=headless, executable_path=exe)
            page = browser.new_page(user_agent=USER_AGENT)
            page.set_default_timeout(60_000)

            consecutive_failures = 0
            for year in range(year_from, year_to + 1):
                endpoint_desc = f"{SEARCH_URL} uni={inst.yok_university_name} year={year}"
                try:
                    page.goto(SEARCH_URL, wait_until="domcontentloaded")
                    time.sleep(ACTION_PAUSE)
                    # Detaylı Tarama tab
                    page.click("text=Detaylı Tarama")
                    time.sleep(ACTION_PAUSE)
                    # University: the form uses a popup picker bound to
                    # 'Üniversite'; fall back to a plain input if present.
                    uni_input = page.locator("input[name='uniad'], input[id*='niversite']").first
                    uni_input.fill(inst.yok_university_name)
                    # Year range
                    page.select_option("select[name='yil1']", str(year))
                    page.select_option("select[name='yil2']", str(year))
                    time.sleep(ACTION_PAUSE)
                    page.click("input[type='submit'], button:has-text('Bul')")
                    page.wait_for_load_state("networkidle")
                    time.sleep(ACTION_PAUSE)

                    page_no, n_year = 1, 0
                    while True:
                        html = page.content()
                        (raw_dir / f"{inst.institution_id}_{year}_p{page_no}.html").write_text(
                            html, encoding="utf-8")
                        got = parse_results_html(html, inst, year)
                        records.extend(got)
                        n_year += len(got)
                        nxt = page.locator("a:has-text('Sonraki'), a:has-text('>>')").first
                        if nxt.count() == 0 or not nxt.is_visible():
                            break
                        nxt.click()
                        page.wait_for_load_state("networkidle")
                        time.sleep(ACTION_PAUSE)
                        page_no += 1

                    log.add("yok", endpoint_desc, "ok" if n_year else "ok_empty",
                            institution=inst.institution_en, records_returned=n_year,
                            http_status=200,
                            note=f"{page_no} result page(s); selectors need live verification")
                except Exception as e:  # navigation/selector failures are per-year, logged, never guessed around
                    log.add("yok", endpoint_desc, "failed", institution=inst.institution_en,
                            error=f"{type(e).__name__}: {e}")
                    consecutive_failures += 1
                    if consecutive_failures >= 2:
                        log.add("yok", SEARCH_URL, "failed", institution=inst.institution_en,
                                error="aborting remaining years after 2 consecutive failures "
                                      "(host unreachable or site structure changed)")
                        break
                    continue
                else:
                    consecutive_failures = 0
            browser.close()
    except Exception as e:
        log.add("yok", SEARCH_URL, "failed", institution=inst.institution_en,
                error=f"browser launch/session failed: {type(e).__name__}: {e}")
    return records
