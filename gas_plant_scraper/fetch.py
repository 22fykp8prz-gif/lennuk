"""Polite HTTP fetching: rate limiting, retries, robots.txt, size caps."""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "GasPlantResearchBot/0.1 (public planning/EIA document research; "
    "contact via repository)"
)

MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200 MB per file


class Fetcher:
    def __init__(
        self,
        delay_seconds: float = 2.0,
        timeout: int = 30,
        respect_robots: bool = True,
        max_retries: int = 3,
    ):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay = delay_seconds
        self.timeout = timeout
        self.respect_robots = respect_robots
        self.max_retries = max_retries
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_request_at: dict[str, float] = {}

    # ── robots.txt ────────────────────────────────────────────────────────
    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        host = urlparse(url).netloc
        if host not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            robots_url = f"{urlparse(url).scheme}://{host}/robots.txt"
            try:
                resp = self.session.get(robots_url, timeout=self.timeout)
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                    self._robots[host] = parser
                else:
                    self._robots[host] = None
            except requests.RequestException:
                self._robots[host] = None
        return self._robots[host]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parser = self._robots_for(url)
        return parser is None or parser.can_fetch(USER_AGENT, url)

    # ── fetching ──────────────────────────────────────────────────────────
    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        elapsed = time.monotonic() - self._last_request_at.get(host, 0.0)
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_at[host] = time.monotonic()

    def get(self, url: str, stream: bool = False) -> requests.Response | None:
        """GET with throttling and exponential-backoff retries; None on failure."""
        if not self.allowed(url):
            log.info("robots.txt disallows %s", url)
            return None
        backoff = 2.0
        for attempt in range(1, self.max_retries + 1):
            self._throttle(url)
            try:
                resp = self.session.get(url, timeout=self.timeout, stream=stream)
                if resp.status_code in (429, 502, 503, 504):
                    raise requests.RequestException(f"HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    log.info("HTTP %s for %s", resp.status_code, url)
                    return None
                return resp
            except requests.RequestException as exc:
                log.warning("attempt %d failed for %s: %s", attempt, url, exc)
                if attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
        return None

    def download(self, url: str, dest_path: str) -> int | None:
        """Stream a file to disk. Returns byte count, or None on failure."""
        resp = self.get(url, stream=True)
        if resp is None:
            return None
        written = 0
        try:
            with open(dest_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        log.warning("size cap exceeded, aborting %s", url)
                        return None
                    fh.write(chunk)
        except requests.RequestException as exc:
            log.warning("download failed for %s: %s", url, exc)
            return None
        finally:
            resp.close()
        return written
