"""Supabase client stub for base_links table (Phase 1d)."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class SupabaseClient:
    def __init__(
        self,
        *,
        url: str | None = None,
        service_role_key: str | None = None,
    ) -> None:
        self.url = url or os.getenv("SUPABASE_URL")
        self.service_role_key = service_role_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        self._client: Any = None

        if not self.url or not self.service_role_key:
            logger.warning(
                "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set — stub mode."
            )

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.service_role_key)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.is_configured:
            raise RuntimeError(
                "Supabase not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
            )
        from supabase import create_client

        self._client = create_client(self.url, self.service_role_key)
        return self._client

    def insert_base_link(self, record: dict[str, Any]) -> dict[str, Any] | None:
        if not self.is_configured:
            logger.debug("Stub insert_base_link: %s", record.get("url"))
            return None
        client = self._get_client()
        response = client.table("base_links").insert(record).execute()
        return response.data[0] if response.data else None

    def upsert_base_link(self, record: dict[str, Any]) -> dict[str, Any] | None:
        if not self.is_configured:
            logger.debug("Stub upsert_base_link: %s", record.get("url"))
            return None
        client = self._get_client()
        response = client.table("base_links").upsert(record, on_conflict="url").execute()
        return response.data[0] if response.data else None

    def get_base_links(
        self,
        *,
        limit: int = 100,
        decode_status: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_configured:
            logger.debug("Stub get_base_links(limit=%d)", limit)
            return []
        client = self._get_client()
        query = client.table("base_links").select("*").limit(limit)
        if decode_status:
            query = query.eq("decode_status", decode_status)
        response = query.execute()
        return response.data or []
