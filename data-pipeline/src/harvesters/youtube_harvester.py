"""YouTube harvester — search CoC base videos and extract share links."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import httpx

from harvesters.base_registry import BaseLink, BaseRegistry

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

COC_LINK_PATTERN = re.compile(
    r"https?://link\.clashofclans\.com/[A-Za-z0-9/?=&_%\-]+",
    re.IGNORECASE,
)

DEFAULT_SEARCH_QUERIES = [
    "clash of clans war base",
    "clash of clans TH18 base",
    "clash of clans TH17 base",
    "clash of clans TH16 base",
    "clash of clans anti 3 star base",
    "coc base layout link",
    "clash of clans base copy link",
]

DEFAULT_REQUEST_DELAY_SEC = float(os.getenv("HARVESTER_REQUEST_DELAY_SEC", "1.0"))


class YouTubeHarvester:
    """Search YouTube Data API v3 for CoC base videos and extract share links."""

    def __init__(
        self,
        registry: BaseRegistry,
        *,
        api_key: str | None = None,
        request_delay_sec: float = DEFAULT_REQUEST_DELAY_SEC,
    ) -> None:
        self.registry = registry
        self.api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self.request_delay_sec = request_delay_sec
        self._client = httpx.Client(timeout=30.0)

    def harvest(
        self,
        *,
        queries: list[str] | None = None,
        max_results_per_query: int = 25,
    ) -> int:
        """Run search queries and register discovered share links. Returns new link count."""
        if not self.api_key:
            logger.error(
                "YOUTUBE_API_KEY is not set. "
                "TODO: obtain a YouTube Data API v3 key and export YOUTUBE_API_KEY."
            )
            return 0

        queries = queries or DEFAULT_SEARCH_QUERIES
        total_new = 0
        for query in queries:
            logger.info("YouTube search: %r", query)
            video_ids = self._search_videos(query, max_results=max_results_per_query)
            for video_id in video_ids:
                links = self._extract_links_from_video(video_id)
                total_new += self.registry.add_many(links)
                self._sleep()
        return total_new

    def _search_videos(self, query: str, *, max_results: int) -> list[str]:
        params: dict[str, Any] = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(max_results, 50),
            "key": self.api_key,
            "relevanceLanguage": "en",
        }
        try:
            response = self._client.get(YOUTUBE_SEARCH_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("YouTube search failed for %r: %s", query, exc)
            return []

        items = response.json().get("items", [])
        return [
            item["id"]["videoId"]
            for item in items
            if item.get("id", {}).get("videoId")
        ]

    def _extract_links_from_video(self, video_id: str) -> list[BaseLink]:
        params = {
            "part": "snippet",
            "id": video_id,
            "key": self.api_key,
        }
        try:
            response = self._client.get(YOUTUBE_VIDEOS_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("YouTube video fetch failed for %s: %s", video_id, exc)
            return []

        items = response.json().get("items", [])
        if not items:
            return []

        snippet = items[0].get("snippet", {})
        description = snippet.get("description", "")
        channel = snippet.get("channelTitle")
        title = snippet.get("title")

        links: list[BaseLink] = []
        for match in COC_LINK_PATTERN.finditer(description):
            url = match.group(0).rstrip(").,]")
            links.append(
                BaseLink(
                    url=url,
                    source="youtube",
                    discovered_at=BaseLink.now_iso(),
                    channel=channel,
                    video_id=video_id,
                    page_url=f"https://www.youtube.com/watch?v={video_id}",
                    title=title,
                )
            )
        if not links:
            logger.debug("No CoC links in video %s (%s)", video_id, title)
        return links

    def _sleep(self) -> None:
        if self.request_delay_sec > 0:
            time.sleep(self.request_delay_sec)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "YouTubeHarvester":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
