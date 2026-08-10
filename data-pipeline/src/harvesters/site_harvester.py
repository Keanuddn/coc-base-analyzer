"""Site harvester — polite crawling of community layout sites."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import yaml

from harvesters.base_registry import BaseLink, BaseRegistry

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = os.getenv(
    "HARVESTER_USER_AGENT",
    "CoCBaseAnalyzer/0.1 (+https://github.com/coc-base-analyzer)",
)
DEFAULT_REQUEST_DELAY_SEC = float(os.getenv("HARVESTER_REQUEST_DELAY_SEC", "1.0"))
MAX_CONCURRENT_PER_HOST = 3
MAX_BACKOFF_SEC = 60.0

COC_LINK_PATTERN = re.compile(
    r"https?://link\.clashofclans\.com/[A-Za-z0-9/?=&_%\-]+",
    re.IGNORECASE,
)
PREVIEW_IMAGE_PATTERN = re.compile(
    r"""<img[^>]+src=["']([^"']+(?:layout|base|preview|thumb)[^"']*)["']""",
    re.IGNORECASE,
)

BLOCKED_DOMAINS_PATH = Path(__file__).with_name("blocked_domains.yaml")


class BlockedDomainsStore:
    def __init__(self, path: Path = BLOCKED_DOMAINS_PATH) -> None:
        self.path = path
        self._domains: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._domains = {}
            return
        with self.path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        for entry in data.get("domains", []) or []:
            domain = entry.get("domain", "").lower()
            if domain:
                self._domains[domain] = entry

    def is_blocked(self, domain: str) -> bool:
        return domain.lower() in self._domains

    def add(self, domain: str, *, reason: str, user_agent: str) -> None:
        domain = domain.lower()
        if domain in self._domains:
            return
        entry = {
            "domain": domain,
            "reason": reason,
            "blocked_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "user_agent": user_agent,
        }
        self._domains[domain] = entry
        self._save()
        logger.info("Blocked domain %s: %s", domain, reason)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"domains": list(self._domains.values())}
        with self.path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)

    @property
    def domains(self) -> list[dict[str, str]]:
        return list(self._domains.values())


class RobotsChecker:
    def __init__(self, user_agent: str, client: httpx.AsyncClient) -> None:
        self.user_agent = user_agent
        self.client = client
        self._cache: dict[str, RobotFileParser | None] = {}

    async def can_fetch(self, url: str) -> tuple[bool, str]:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain not in self._cache:
            self._cache[domain] = await self._fetch_robots(parsed)
        rp = self._cache[domain]
        if rp is None:
            return True, "no robots.txt"
        allowed = rp.can_fetch(self.user_agent, url)
        if allowed:
            return True, "allowed by robots.txt"
        return False, f"robots.txt disallows {parsed.path or '/'} for {self.user_agent!r}"

    async def _fetch_robots(self, parsed: Any) -> RobotFileParser | None:
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            response = await self.client.get(robots_url, follow_redirects=True)
            if response.status_code >= 400:
                return None
            rp = RobotFileParser()
            rp.parse(response.text.splitlines())
            return rp
        except httpx.HTTPError as exc:
            logger.warning("robots.txt fetch failed for %s: %s", parsed.netloc, exc)
            return None


class HostRateLimiter:
    def __init__(self, max_concurrent: int, delay_sec: float) -> None:
        self.max_concurrent = max_concurrent
        self.delay_sec = delay_sec
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}

    def semaphore_for(self, domain: str) -> asyncio.Semaphore:
        domain = domain.lower()
        if domain not in self._semaphores:
            self._semaphores[domain] = asyncio.Semaphore(self.max_concurrent)
        return self._semaphores[domain]

    async def wait_turn(self, domain: str) -> None:
        domain = domain.lower()
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        async with self._locks[domain]:
            loop = asyncio.get_running_loop()
            now = loop.time()
            last = self._last_request.get(domain, 0.0)
            wait = self.delay_sec - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request[domain] = loop.time()


class SiteHarvester:
    def __init__(
        self,
        registry: BaseRegistry,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        request_delay_sec: float = DEFAULT_REQUEST_DELAY_SEC,
        blocked_store: BlockedDomainsStore | None = None,
    ) -> None:
        self.registry = registry
        self.user_agent = user_agent
        self.request_delay_sec = request_delay_sec
        self.blocked_store = blocked_store or BlockedDomainsStore()
        self.rate_limiter = HostRateLimiter(MAX_CONCURRENT_PER_HOST, request_delay_sec)

    async def harvest(self, seed_urls: list[str]) -> int:
        headers = {"User-Agent": self.user_agent}
        total_new = 0
        async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
            robots = RobotsChecker(self.user_agent, client)
            for url in seed_urls:
                domain = urlparse(url).netloc.lower()
                if self.blocked_store.is_blocked(domain):
                    logger.info("Skipping blocked domain: %s", domain)
                    continue
                total_new += await self._crawl_page(url, client, robots)
        return total_new

    async def _crawl_page(
        self,
        url: str,
        client: httpx.AsyncClient,
        robots: RobotsChecker,
    ) -> int:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        if self.blocked_store.is_blocked(domain):
            logger.info("Skipping blocked domain: %s", domain)
            return 0

        allowed, reason = await robots.can_fetch(url)
        if not allowed:
            self.blocked_store.add(domain, reason=reason, user_agent=self.user_agent)
            return 0

        sem = self.rate_limiter.semaphore_for(domain)
        async with sem:
            await self.rate_limiter.wait_turn(domain)
            html = await self._fetch_with_backoff(client, url)
        if html is None:
            return 0

        links = self._extract_links(html, url)
        preview = self._extract_preview_image(html, url)
        for link in links:
            if preview and not link.preview_image_url:
                link.preview_image_url = preview
        return self.registry.add_many(links)

    async def _fetch_with_backoff(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        attempt: int = 0,
    ) -> str | None:
        try:
            response = await client.get(url)
            if response.status_code in (429, 503):
                if attempt >= 5:
                    logger.error("Max backoff retries for %s", url)
                    return None
                delay = min(2**attempt * self.request_delay_sec, MAX_BACKOFF_SEC)
                logger.warning("HTTP %s for %s — backing off %.1fs", response.status_code, url, delay)
                await asyncio.sleep(delay)
                return await self._fetch_with_backoff(client, url, attempt=attempt + 1)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            logger.error("Fetch failed for %s: %s", url, exc)
            return None

    def _extract_links(self, html: str, page_url: str) -> list[BaseLink]:
        site = BaseRegistry.source_from_url(page_url)
        seen: set[str] = set()
        links: list[BaseLink] = []
        for match in COC_LINK_PATTERN.finditer(html):
            url = match.group(0).rstrip("\"'<>).,]")
            if url in seen:
                continue
            seen.add(url)
            links.append(
                BaseLink(
                    url=url,
                    source=site,
                    discovered_at=BaseLink.now_iso(),
                    site=site,
                    page_url=page_url,
                )
            )
        return links

    def _extract_preview_image(self, html: str, page_url: str) -> str | None:
        match = PREVIEW_IMAGE_PATTERN.search(html)
        if not match:
            return None
        return urljoin(page_url, match.group(1))
