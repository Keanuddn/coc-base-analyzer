"""Local registry for harvested CoC base share links.

Inspired by the JSONL registry pattern used in community projects such as
nschmeller/clash-bases: append-only records, URL deduplication, and rich
source metadata for downstream decoding and rendering.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

COC_SHARE_LINK_PREFIX = "https://link.clashofclans.com/"


@dataclass(slots=True)
class BaseLink:
    """A harvested link.clashofclans.com share URL with provenance."""

    url: str
    source: str  # e.g. "youtube", "clashofclanslayouts.org"
    discovered_at: str  # ISO-8601 UTC
    channel: str | None = None
    site: str | None = None
    video_id: str | None = None
    page_url: str | None = None
    preview_image_url: str | None = None
    title: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.url.startswith(COC_SHARE_LINK_PREFIX):
            raise ValueError(f"Not a CoC share link: {self.url}")
        if self.source == "youtube" and not self.channel and not self.video_id:
            logger.warning("YouTube BaseLink missing channel/video_id: %s", self.url)

    @classmethod
    def now_iso(cls) -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaseLink:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        core = {k: v for k, v in data.items() if k in known}
        extra = data.get("extra") or {k: v for k, v in data.items() if k not in known}
        core.setdefault("extra", extra)
        return cls(**core)


class BaseRegistry:
    """Append-only JSONL registry with in-memory URL deduplication."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen_urls: set[str] = set()
        self._load_existing()

    def _load_existing(self) -> None:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    self._seen_urls.add(record["url"])
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("Skipping corrupt registry line %d: %s", line_no, exc)

    def add(self, link: BaseLink) -> bool:
        """Append link if URL is new. Returns True when inserted."""
        if link.url in self._seen_urls:
            logger.debug("Duplicate skipped: %s", link.url)
            return False
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(link.to_dict(), ensure_ascii=False) + "\n")
        self._seen_urls.add(link.url)
        logger.info("Registered base link from %s: %s", link.source, link.url)
        return True

    def add_many(self, links: list[BaseLink]) -> int:
        return sum(1 for link in links if self.add(link))

    @property
    def count(self) -> int:
        return len(self._seen_urls)

    def iter_links(self) -> list[BaseLink]:
        if not self.path.exists():
            return []
        links: list[BaseLink] = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    links.append(BaseLink.from_dict(json.loads(line)))
        return links

    @staticmethod
    def source_from_url(url: str) -> str:
        host = urlparse(url).netloc.lower()
        return host.removeprefix("www.")
