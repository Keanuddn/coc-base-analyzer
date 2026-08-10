"""Tests for robots.txt compliance and blocked domain registry."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import yaml

from harvesters.base_registry import BaseRegistry
from harvesters.site_harvester import BlockedDomainsStore, RobotsChecker, SiteHarvester


@pytest.fixture
def registry(tmp_path: Path) -> BaseRegistry:
    return BaseRegistry(tmp_path / "links.jsonl")


@pytest.fixture
def blocked_path(tmp_path: Path) -> Path:
    return tmp_path / "blocked_domains.yaml"


def test_blocked_domains_store_persists_entry(blocked_path: Path) -> None:
    store = BlockedDomainsStore(blocked_path)
    store.add("example.com", reason="robots.txt disallows /", user_agent="TestBot/1.0")

    reloaded = BlockedDomainsStore(blocked_path)
    assert reloaded.is_blocked("example.com")
    assert reloaded.is_blocked("EXAMPLE.COM")

    with blocked_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert len(data["domains"]) == 1
    entry = data["domains"][0]
    assert entry["domain"] == "example.com"
    assert entry["reason"] == "robots.txt disallows /"
    assert entry["blocked_at"].endswith("Z")
    assert entry["user_agent"] == "TestBot/1.0"


def test_blocked_domains_store_starts_empty(blocked_path: Path) -> None:
    blocked_path.write_text("domains: []\n", encoding="utf-8")
    store = BlockedDomainsStore(blocked_path)
    assert not store.is_blocked("any.example")


@pytest.mark.asyncio
async def test_robots_checker_respects_disallow() -> None:
    robots_txt = textwrap.dedent(
        """
        User-agent: *
        Disallow: /layouts/
        Allow: /
        """
    )
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = robots_txt

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get.return_value = mock_response

    checker = RobotsChecker("CoCBaseAnalyzer/0.1", client)
    allowed, _ = await checker.can_fetch("https://example.com/")
    assert allowed is True

    blocked, reason = await checker.can_fetch("https://example.com/layouts/th18")
    assert blocked is False
    assert "disallows" in reason


@pytest.mark.asyncio
async def test_site_harvester_skips_blocked_domain(registry: BaseRegistry, blocked_path: Path) -> None:
    store = BlockedDomainsStore(blocked_path)
    store.add("blocked.test", reason="manual block", user_agent="TestBot/1.0")

    harvester = SiteHarvester(registry, blocked_store=store)

    with patch.object(harvester, "_crawl_page", new_callable=AsyncMock) as mock_crawl:
        count = await harvester.harvest(["https://blocked.test/page"])
        mock_crawl.assert_not_called()
        assert count == 0


@pytest.mark.asyncio
async def test_site_harvester_extracts_links(registry: BaseRegistry, blocked_path: Path) -> None:
    html = """
    <html><body>
      <a href="https://link.clashofclans.com/en?clan=abc&tag=XYZ&token=deadbeef">Copy</a>
      <img src="/images/layout-preview.png" alt="layout preview">
    </body></html>
    """
    harvester = SiteHarvester(registry, blocked_store=BlockedDomainsStore(blocked_path))

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()
    mock_client.get.return_value = mock_response

    robots = RobotsChecker("TestBot/1.0", mock_client)
    with patch.object(robots, "can_fetch", new=AsyncMock(return_value=(True, "allowed"))):
        count = await harvester._crawl_page(
            "https://clashofclanslayouts.org/layout/123",
            mock_client,
            robots,
        )

    assert count == 1
    assert registry.count == 1
    link = registry.iter_links()[0]
    assert link.url.startswith("https://link.clashofclans.com/")
    assert link.site == "clashofclanslayouts.org"
