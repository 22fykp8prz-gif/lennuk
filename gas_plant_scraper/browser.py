"""Optional Playwright-based page rendering for JavaScript-heavy portals
(PLANK, ylupa.avi.fi, ĢeoLatvija, TPDRIS ...).

The renderer opens the page in headless Chromium, waits for the SPA to load
its content, and returns the rendered HTML, which the normal crawler then
parses like any other page. Playwright is optional: when it is not
installed, sources marked ``render: true`` fall back to plain HTTP.
"""

from __future__ import annotations

import logging
import os
import time

log = logging.getLogger(__name__)

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

# Resource types the SPA does not need for producing its DOM; skipping them
# speeds rendering up and keeps the load on the portal low.
_BLOCKED_RESOURCES = {"image", "media", "font"}

# Well-known Chromium location in some managed environments; used as a
# fallback when Playwright's own browser download is missing.
_FALLBACK_CHROMIUM = "/opt/pw-browsers/chromium"


def available() -> bool:
    return sync_playwright is not None


class Renderer:
    """Renders pages in headless Chromium, one at a time, politely."""

    def __init__(
        self,
        delay_seconds: float = 2.0,
        timeout_ms: int = 30000,
        settle_ms: int = 2000,
        user_agent: str | None = None,
    ):
        if sync_playwright is None:  # pragma: no cover
            raise RuntimeError(
                "playwright pole paigaldatud (pip install playwright "
                "&& playwright install chromium)"
            )
        self.delay = delay_seconds
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms
        self.user_agent = user_agent
        self._pw = None
        self._browser = None
        self._context = None
        self._last_render_at = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────
    def _launch(self) -> None:
        self._pw = sync_playwright().start()
        executable = os.environ.get("GPS_CHROMIUM_PATH")
        try:
            self._browser = self._pw.chromium.launch(executable_path=executable)
        except PlaywrightError:
            if executable or not os.path.exists(_FALLBACK_CHROMIUM):
                raise
            log.info("using fallback Chromium at %s", _FALLBACK_CHROMIUM)
            self._browser = self._pw.chromium.launch(
                executable_path=_FALLBACK_CHROMIUM
            )
        self._context = self._browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1440, "height": 900},
        )
        self._context.route(
            "**/*",
            lambda route: (
                route.abort()
                if route.request.resource_type in _BLOCKED_RESOURCES
                else route.continue_()
            ),
        )

    def _ensure_started(self) -> None:
        if self._context is None:
            self._launch()

    def close(self) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except PlaywrightError:  # pragma: no cover
                pass
        if self._pw is not None:
            self._pw.stop()
        self._pw = self._browser = self._context = None

    def __enter__(self) -> "Renderer":
        self._ensure_started()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ── rendering ─────────────────────────────────────────────────────────
    def get_html(self, url: str) -> str | None:
        """Return the rendered DOM of ``url``, or None on failure."""
        self._ensure_started()
        elapsed = time.monotonic() - self._last_render_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_render_at = time.monotonic()

        page = self._context.new_page()
        try:
            page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
            try:
                # SPAs keep fetching after DOMContentLoaded; wait for the
                # network to go quiet, but don't fail the page if it never
                # does (long-polling, analytics).
                page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            except PlaywrightTimeout:
                log.debug("networkidle timeout for %s, using current DOM", url)
            if self.settle_ms:
                page.wait_for_timeout(self.settle_ms)
            return page.content()
        except (PlaywrightError, PlaywrightTimeout) as exc:
            log.warning("render failed for %s: %s", url, exc)
            return None
        finally:
            page.close()
