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

# The advanced-search entry point has been labelled differently over time.
DETAILED_SEARCH_LABELS = ["Detaylı Tarama", "Detaylı Arama", "Gelişmiş Tarama", "Gelişmiş Arama"]


def _click_any_label(page, labels: list[str], timeout_ms: int = 10_000) -> str | None:
    """Try to click the first matching label, searching the page and every
    frame (the site historically used framesets). Returns the label that
    worked, or None."""
    contexts = [page] + [f for f in page.frames if f != page.main_frame]
    for ctx in contexts:
        for label in labels:
            loc = ctx.locator(f"text={label}")
            try:
                if loc.count() > 0:
                    loc.first.click(timeout=timeout_ms)
                    return label
            except Exception:
                continue
    return None


def _dump_debug(page, raw_dir: Path, tag: str) -> str:
    """Save screenshot + HTML of the current page so a failing selector can
    be diagnosed offline. Returns the path prefix."""
    prefix = raw_dir / f"debug_{tag}"
    try:
        page.screenshot(path=f"{prefix}.png", full_page=True)
    except Exception:
        pass
    try:
        Path(f"{prefix}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    return str(prefix)


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


def debug_page(out_dir: Path) -> None:
    """Open the YÖK search page and print an inventory of what is actually
    on it (frames, link texts, form fields), plus save a screenshot. This is
    what turns 'selector not found' into a concrete fix."""
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        page.set_default_timeout(60_000)
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        time.sleep(5)

        print(f"URL now: {page.url}")
        print(f"Page title: {page.title()!r}")
        print(f"Frames: {[f.url for f in page.frames]}")

        def inventory(ctx, label):
            links = [_clean(t) for t in ctx.locator("a").all_text_contents()]
            links = [t for t in links if t][:60]
            print(f"\n[{label}] link texts ({len(links)} shown):")
            for t in dict.fromkeys(links):
                print(f"  - {t}")
            fields = ctx.locator("input, select, button")
            n = min(fields.count(), 40)
            print(f"[{label}] form fields ({n} shown):")
            for i in range(n):
                el = fields.nth(i)
                try:
                    print(f"  - <{el.evaluate('e => e.tagName')}> name={el.get_attribute('name')!r} "
                          f"id={el.get_attribute('id')!r} type={el.get_attribute('type')!r} "
                          f"value={(el.get_attribute('value') or '')[:30]!r}")
                except Exception:
                    pass

        inventory(page, "main")
        for f in page.frames:
            if f != page.main_frame:
                inventory(f, f"frame {f.url}")

        # Forms: their action URLs reveal where searches actually POST to
        # (a possible future path to skipping the browser entirely).
        forms = page.locator("form")
        print(f"\nForms ({forms.count()}):")
        for i in range(forms.count()):
            f = forms.nth(i)
            print(f"  action={f.get_attribute('action')!r} method={f.get_attribute('method')!r} "
                  f"id={f.get_attribute('id')!r} name={f.get_attribute('name')!r}")

        # Selects with sample options (year dropdowns, thesis-type filter).
        sels = page.locator("select")
        print(f"\nSelects ({sels.count()}):")
        for i in range(min(sels.count(), 15)):
            s = sels.nth(i)
            opts = [_clean(t) for t in s.locator("option").all_text_contents()][:8]
            print(f"  name={s.get_attribute('name')!r} id={s.get_attribute('id')!r} options[:8]={opts}")

        # Simulate the university picker with a real name and show what appears.
        si = page.locator("#search-input")
        if si.count():
            print("\nTyping 'İSTANBUL TEKNİK ÜNİVERSİTESİ' into #search-input ...")
            try:
                si.first.fill("İSTANBUL TEKNİK ÜNİVERSİTESİ")
                time.sleep(3)
                items = [_clean(t) for t in page.locator("li").all_text_contents() if _clean(t)][:30]
                print(f"list items now visible: {items}")
                for hidden_id in ("#uniad", "#Universite", "#uni_yoksis_id"):
                    loc = page.locator(hidden_id)
                    if loc.count():
                        print(f"hidden {hidden_id} = {loc.first.input_value()!r}")
                _dump_debug(page, out_dir, "yok_typed")
            except Exception as e:
                print(f"simulation failed: {type(e).__name__}: {e}")
        else:
            print("\n#search-input not present on this layout")

        prefix = _dump_debug(page, out_dir, "yok_debug")
        print(f"\nScreenshot + HTML saved: {prefix}.png / {prefix}.html")
        browser.close()


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
                    # tarama.jsp *is* the search screen in the current layout
                    # (title "Arama Ekranları"); older layouts had an advanced
                    # tab — click it if present, ignore if not.
                    _click_any_label(page, DETAILED_SEARCH_LABELS, timeout_ms=3000)

                    # University picker: type into the autocomplete, accept a
                    # suggestion, then VERIFY the hidden fields got populated.
                    # Searching without a university filter would silently
                    # misattribute the whole result set — hard fail instead.
                    si = page.locator("#search-input")
                    if si.count() == 0:
                        prefix = _dump_debug(page, raw_dir, f"{inst.institution_id}_{year}_entry")
                        raise RuntimeError(
                            f"university autocomplete (#search-input) not found; "
                            f"snapshot {prefix}.png/.html — run `python -m harvester yok-debug`"
                        )
                    si.first.fill(inst.yok_university_name)
                    time.sleep(2)
                    suggestion = page.locator(f"li:has-text('{inst.yok_university_name}')")
                    if suggestion.count() > 0:
                        suggestion.first.click()
                    else:
                        si.first.press("ArrowDown")
                        si.first.press("Enter")
                    time.sleep(1)
                    picked = ""
                    for hidden_id in ("#uniad", "#Universite", "#uni_yoksis_id"):
                        loc = page.locator(hidden_id)
                        if loc.count():
                            try:
                                picked += loc.first.input_value() or ""
                            except Exception:
                                pass
                    if not picked.strip():
                        prefix = _dump_debug(page, raw_dir, f"{inst.institution_id}_{year}_picker")
                        raise RuntimeError(
                            "university picker did not populate uniad/uni_yoksis_id — "
                            f"refusing to search unfiltered; snapshot {prefix}.png/.html"
                        )
                    # Year range, where the form exposes it.
                    for sel_name in ("yil1", "yil2"):
                        sel = page.locator(f"select[name='{sel_name}']")
                        if sel.count():
                            sel.first.select_option(str(year))
                    time.sleep(ACTION_PAUSE)
                    page.click("button[name='-find'], button:has-text('Bul'), input[type='submit']")
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
