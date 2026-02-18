from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class BookStackCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch BookStack stats and per-shelf book counts."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        config: dict[str, Any],
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        per_shelf_enabled: bool = True,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="BookStack",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.session = session
        self.config = config
        self.per_shelf_enabled = per_shelf_enabled
        self.version: str | None = None
        self.system_data: dict[str, Any] = {}
        self.shelves_data: list[dict[str, Any]] = []
        self.last_updated_page: dict[str, Any] = {}
        self.is_available: bool = False
        # Silver: log-when-unavailable — track previous availability so we log
        # exactly once on transition, not on every failed poll.
        self._was_available: bool | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from BookStack API."""
        headers = {
            "Authorization": f"Token {self.config['token_id']}:{self.config['token_secret']}"
        }
        base_url = self.config["url"].rstrip("/")

        timeout = aiohttp.ClientTimeout(total=10)

        async def get_json(endpoint: str) -> dict[str, Any]:
            url = f"{base_url}/api/{endpoint.lstrip('/')}"
            async with self.session.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed("Invalid API credentials")
                if resp.status != 200:
                    raise UpdateFailed(f"API error {resp.status} for {endpoint}")
                return await resp.json()

        async def count(endpoint: str) -> int:
            data = await get_json(f"{endpoint}?count=1")
            return data.get("total", 0)

        async def get_all_shelves() -> list[dict[str, Any]]:
            all_shelves: list[dict[str, Any]] = []
            offset = 0
            page_size = 100
            while True:
                response = await get_json(f"shelves?count={page_size}&offset={offset}")
                batch = response.get("data", [])
                all_shelves.extend(batch)
                if len(all_shelves) >= response.get("total", 0) or not batch:
                    break
                offset += page_size
            return all_shelves

        try:
            # System info
            self.system_data = await get_json("system")
            self.version = self.system_data.get("version", "Unknown")

            # Standard counts
            data: dict[str, Any] = {
                "shelves": await count("shelves"),
                "books": await count("books"),
                "chapters": await count("chapters"),
                "pages": await count("pages"),
                "users": await count("users"),
                "images": await count("image-gallery"),
                "attachments": await count("attachments",)
            }

            # Last updated page
            pages_response = await get_json("pages?sort=-updated_at&count=1")
            pages_list = pages_response.get("data", [])
            if pages_list:
                page_detail = await get_json(f"pages/{pages_list[0]['id']}")
                updated_by = page_detail.get("updated_by") or {}
                self.last_updated_page = {
                    "id": page_detail.get("id"),
                    "name": page_detail.get("name"),
                    "updated_at": page_detail.get("updated_at"),
                    "updated_by_name": updated_by.get("name"),
                    "updated_by_id": updated_by.get("id"),
                    "url": (
                        f"{base_url}/books/{page_detail.get('book_id')}"
                        f"/page/{page_detail.get('slug', '')}"
                    ),
                }
            else:
                self.last_updated_page = {}

            # Per-shelf sensors
            self.shelves_data = []
            if self.per_shelf_enabled:
                shelf_summaries = await get_all_shelves()
                shelves = []
                for shelf_summary in shelf_summaries:
                    shelf_detail = await get_json(f"shelves/{shelf_summary['id']}")
                    books = shelf_detail.get("books", [])

                    chapter_count = 0
                    page_count = 0
                    for book in books:
                        book_detail = await get_json(f"books/{book['id']}")
                        for item in book_detail.get("contents", []):
                            if item.get("type") == "chapter":
                                chapter_count += 1
                            elif item.get("type") == "page":
                                page_count += 1
                        for item in book_detail.get("contents", []):
                            if item.get("type") == "chapter":
                                page_count += len(item.get("pages", []))

                    shelves.append({
                        "id": shelf_summary["id"],
                        "name": shelf_summary["name"],
                        "book_count": len(books),
                        "chapter_count": chapter_count,
                        "page_count": page_count,
                    })
                self.shelves_data = shelves

            self.is_available = True
            # Silver: log-when-unavailable — log once when back online.
            if self._was_available is False:
                _LOGGER.info("BookStack at %s is back online", base_url)
            self._was_available = True
            return data

        except ConfigEntryAuthFailed:
            self.is_available = False
            self._was_available = False
            raise
        except aiohttp.ClientError as err:
            self.is_available = False
            # Silver: log-when-unavailable — log once when connection is lost.
            if self._was_available is not False:
                _LOGGER.warning(
                    "BookStack at %s is unavailable: %s", base_url, err
                )
            self._was_available = False
            raise UpdateFailed(f"Connection error: {err}") from err