"""Polite HTTP client: per-host rate limiting, disk caching, exponential backoff.

Raw responses are cached to disk before parsing so re-runs are idempotent and
a crash mid-harvest never means re-hitting the source from scratch.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import BACKOFF_SCHEDULE, MIN_INTERVAL_PER_HOST, USER_AGENT


class HarvestError(Exception):
    """A source could not be fetched. `kind` classifies the failure."""

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind  # egress_blocked | http_error | network_error | robots_disallowed
        self.status = status


@dataclass
class FetchResult:
    url: str
    status: int
    body: bytes
    from_cache: bool

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _is_egress_denial(exc: Exception) -> bool:
    # The managed environment's egress proxy answers CONNECT with 403 for
    # hosts outside the org's network policy. Retrying is pointless and
    # explicitly discouraged; classify so callers log it as a policy block.
    s = str(exc)
    return "403" in s and ("CONNECT" in s or "ProxyError" in type(exc).__name__ or "Tunnel" in s)


class PoliteClient:
    def __init__(self, cache_dir: Path, offline: bool = False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    # -- caching ------------------------------------------------------------
    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        host = urllib.parse.urlparse(url).netloc or "no-host"
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        d = self.cache_dir / host
        return d / f"{h}.body", d / f"{h}.meta.json"

    def _read_cache(self, url: str) -> FetchResult | None:
        body_p, meta_p = self._cache_paths(url)
        if body_p.exists() and meta_p.exists():
            meta = json.loads(meta_p.read_text())
            if meta["status"] >= 400:
                # Error responses written by older versions must never be
                # replayed as answers; drop and refetch.
                body_p.unlink(missing_ok=True)
                meta_p.unlink(missing_ok=True)
                return None
            return FetchResult(url=url, status=meta["status"], body=body_p.read_bytes(), from_cache=True)
        return None

    def _write_cache(self, url: str, status: int, body: bytes) -> None:
        body_p, meta_p = self._cache_paths(url)
        body_p.parent.mkdir(parents=True, exist_ok=True)
        body_p.write_bytes(body)
        meta_p.write_text(json.dumps({"url": url, "status": status, "fetched_at": time.time()}))

    # -- politeness ---------------------------------------------------------
    def _throttle(self, url: str) -> None:
        host = urllib.parse.urlparse(url).netloc
        last = self._last_request_at.get(host, 0.0)
        wait = MIN_INTERVAL_PER_HOST - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at[host] = time.monotonic()

    def check_robots(self, url: str) -> bool:
        """True if our UA may fetch `url` per robots.txt. Unknown => True,
        but a fetch failure of robots.txt itself is not treated as permission
        for a host we cannot reach at all (the real fetch will fail anyway)."""
        parts = urllib.parse.urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                res = self.get(f"{base}/robots.txt", allow_error_status=True, skip_robots=True)
                if res.status == 200:
                    rp.parse(res.text.splitlines())
                else:
                    rp = None
            except HarvestError:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        if rp is None:
            return True
        return rp.can_fetch(USER_AGENT, url)

    # -- fetching -----------------------------------------------------------
    def get(
        self,
        url: str,
        params: dict | None = None,
        timeout: int = 60,
        allow_error_status: bool = False,
        skip_robots: bool = True,
        use_cache: bool = True,
    ) -> FetchResult:
        """GET with cache, throttle and backoff.

        skip_robots defaults to True because OAI-PMH and documented APIs are
        explicit machine interfaces; HTML scraping paths must pass
        skip_robots=False.
        """
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

        if use_cache:
            cached = self._read_cache(url)
            if cached is not None:
                return cached

        if self.offline:
            raise HarvestError("network_error", f"offline mode, not cached: {url}")

        if not skip_robots and not self.check_robots(url):
            raise HarvestError("robots_disallowed", f"robots.txt disallows {url}")

        attempts = len(BACKOFF_SCHEDULE) + 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            self._throttle(url)
            try:
                resp = self.session.get(url, timeout=timeout)
            except requests.exceptions.ProxyError as e:
                if _is_egress_denial(e):
                    raise HarvestError(
                        "egress_blocked",
                        f"egress proxy denied CONNECT to {urllib.parse.urlparse(url).netloc} "
                        "(organization network policy); host must be allowlisted",
                    ) from e
                last_exc = e
            except requests.exceptions.RequestException as e:
                last_exc = e
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = HarvestError("http_error", f"HTTP {resp.status_code} from {url}", resp.status_code)
                else:
                    # Only successful responses are cached: a cached error
                    # would be replayed as an answer on the next run and
                    # poison it long after the source recovers.
                    if resp.status_code < 400:
                        self._write_cache(url, resp.status_code, resp.content)
                    if resp.status_code >= 400 and not allow_error_status:
                        raise HarvestError("http_error", f"HTTP {resp.status_code} from {url}", resp.status_code)
                    return FetchResult(url=url, status=resp.status_code, body=resp.content, from_cache=False)
            if attempt < attempts - 1:
                time.sleep(BACKOFF_SCHEDULE[attempt])

        if isinstance(last_exc, HarvestError):
            raise last_exc
        raise HarvestError("network_error", f"{type(last_exc).__name__}: {last_exc}") from last_exc
