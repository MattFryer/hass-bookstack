"""Data update coordinator for the BookStack integration.

The coordinator is the central piece of the integration that manages polling the API at the set interval to fetch data and then 
provides that data to the sensor entities. It also handles error handling and availability status. 
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import DEFAULT_SCAN_INTERVAL

# Set up logging for the integration. This allows us to log important information and errors, which can be helpful for debugging and 
# monitoring the integration. Using __name__ produces "custom_components.bookstack" which makes log entries easy to filter in the HA 
# log viewer.
_LOGGER = logging.getLogger(__name__)

class BookStackCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch BookStack stats and per-shelf book counts at the desired interval
    
    Inherits the HA DataUpdateCoordinator, which provides a convenient way to manage periodic data fetching and updating entities. We 
    implement the _async_update_data method to fetch data from the BookStack API, and we can call self.async_refresh() to trigger an 
    update when options change.
    """

    def __init__(
        self,
        hass: HomeAssistant, # The Home Assistant instance, passed in from the async_setup_entry function in __init__.py. This allows the coordinator to interact with HA, such as scheduling updates and logging.
        session: aiohttp.ClientSession, # The shared aiohttp session for making HTTP requests to the BookStack API. This is passed in from async_setup_entry to ensure we reuse HA's session management.
        config: dict[str, Any], # The configuration data from the config entry, which contains the authentication info (URL, token ID, token secret). This is needed to connect to the API.
        scan_interval: int = DEFAULT_SCAN_INTERVAL, # The scan interval in seconds
        per_shelf_enabled: bool = True, # Whether to fetch per-shelf data and create per-shelf sensors. 
    ) -> None:
        """Initialize the coordinator with the necessary parameters."""

        # Initialize the DataUpdateCoordinator with the Home Assistant instance, logger, name, and update interval. The name is used in 
        # logging and error messages to identify which coordinator is reporting issues. The update interval determines how often the 
        # _async_update_data method is called to fetch new data.
        super().__init__(
            hass,
            _LOGGER,
            name="BookStack",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.session = session
        self.config = config
        self.per_shelf_enabled = per_shelf_enabled
        # Instance attributes to hold the fetched data. We initialize them to None or empty structures, and they will be populated 
        # when _async_update_data is called.
        self.version: str | None = None # The version of the BookStack instance, fetched from the /system endpoint.
        self.system_data: dict[str, Any] = {} # The raw system data from the /system endpoint
        self.shelves_data: list[dict[str, Any]] = [] # A list of per-shelf data, including book/chapter/page counts for each shelf, if per_shelf_enabled is True.
        self.last_updated_page: dict[str, Any] = {} # Data about the most recently updated page, including its name, update time, and who updated it.
        self.is_available: bool = False # Availability status of the coordinator, which can be used by entities to determine if they should be marked as unavailable. This is set based on whether we can successfully fetch data from the API.
        self._was_available: bool | None = None # Track the previous availability status to log when the API goes down or comes back up.

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from BookStack API
        
        Called automatically by the DataUpdateCoordinator at the interval specified in the constructor. This method should fetch all 
        necessary data from the BookStack API. It should return a dictionary of the data that will be stored in self.data and made 
        available to entities. If there is an error, it should raise an UpdateFailed exception.
        """

        # Build the headers for authentication using the token ID and secret from the config.
        headers = {
            "Authorization": f"Token {self.config['token_id']}:{self.config['token_secret']}"
        }
        # Get the base URL from the config and ensure it does not end with a slash, as we'll be appending endpoints to it.
        base_url = self.config["url"].rstrip("/")
        # Set a reasonable timeout (10 seconds) for API requests to avoid hanging if the API is unresponsive.
        timeout = aiohttp.ClientTimeout(total=10)

        async def get_json(endpoint: str) -> dict[str, Any]:
            """Helper function to make authenticated GET requests to the API and return the JSON response. Centralises the logic and 
            error handling for API requests."""
            url = f"{base_url}/api/{endpoint.lstrip('/')}"
            async with self.session.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed("Invalid API credentials")
                if resp.status != 200:
                    raise UpdateFailed(f"API error {resp.status} for {endpoint}")
                return await resp.json()

        async def count(endpoint: str) -> int:
            """Helper function to get the total count of items for a given endpoint. Many BookStack API endpoints support a "count" 
            parameter that returns the total number of items, which is more efficient than fetching all items when we only need the 
            count."""
            data = await get_json(f"{endpoint}?count=1")
            return data.get("total", 0)

        async def get_all_shelves() -> list[dict[str, Any]]:
            """Helper function to get a list of all shelves with their IDs and names. The /shelves endpoint is paginated, so we need to 
            loop through pages until we get all shelves. We use this information to create per-shelf sensors if that option is enabled."""
            all_shelves: list[dict[str, Any]] = []
            offset = 0
            page_size = 100 # BookStack has a max page size of 100, so we fetch in batches of 100 until we have all shelves.
            while True:
                response = await get_json(f"shelves?count={page_size}&offset={offset}")
                batch = response.get("data", [])
                all_shelves.extend(batch)
                # Stop if we've fetched all shelves (compared to the total count reported by the API)
                if len(all_shelves) >= response.get("total", 0) or not batch:
                    break
                offset += page_size
            return all_shelves

        # Get all the data we need for the sensors
        try:
            # System info - Gives us the BookStack version and checks the connection/authentication.
            self.system_data = await get_json("system")
            self.version = self.system_data.get("version", "Unknown")

            # Standard counts - Fetches the total counts of shelves, books, chapters, pages, users, images, and attachments using the 
            # count helper function. This is efficient as it avoids fetching all items when we only need the count.
            data: dict[str, Any] = {
                "shelves": await count("shelves"),
                "books": await count("books"),
                "chapters": await count("chapters"),
                "pages": await count("pages"),
                "users": await count("users"),
                "images": await count("image-gallery"),
                "attachments": await count("attachments",)
            }

            # Last updated page - Fetches the single most recently updated page by sorting the /pages endpoint by updated_at in 
            # descending order and taking only the first result. Then we fetch the details of that page to get information about who 
            # updated it and when, which we can use for a "last updated page" sensor.
            pages_response = await get_json("pages?sort=-updated_at&count=1")
            pages_list = pages_response.get("data", [])
            if pages_list:
                page_detail = await get_json(f"pages/{pages_list[0]['id']}") # Fetch the page details to get the updated_by information, which is not included in the list response.
                updated_by = page_detail.get("updated_by") or {} # Handle the case where the updated_by can be null if the user account was deleted in BookStack.
                self.last_updated_page = {
                    "id": page_detail.get("id"),
                    "name": page_detail.get("name"),
                    "updated_at": page_detail.get("updated_at"),
                    "updated_by_name": updated_by.get("name"),
                    "updated_by_id": updated_by.get("id"),
                    # Construct a URL to the page in BookStack using the book ID and page slug, which can be used in the sensor's 
                    # extra attributes to provide a direct link to the page.
                    "url": (
                        f"{base_url}/books/{page_detail.get('book_id')}"
                        f"/page/{page_detail.get('slug', '')}"
                    ),
                }
            else:
                self.last_updated_page = {} # Handle the case where there are no pages in BookStack yet.

            # Per-shelf sensors (Optional) - If the user has enabled per-shelf sensors, we need to fetch the list of shelves and then 
            # for each shelf, fetch the book/chapter/page counts. This is more complex because the API does not provide aggregated 
            # counts for shelves, so we need to fetch the contents of each shelf and count the books, chapters, and pages ourselves. We 
            # also need to handle pagination for the shelves list if there are many shelves. We store the results in self.shelves_data, 
            # which will be used by the per-shelf sensor entities. 
            self.shelves_data = []
            if self.per_shelf_enabled: # Only fetch this data if the option is enabled, as it requires multiple API calls and can be slow if there are many shelves.
                shelf_summaries = await get_all_shelves()
                shelves = []
                for shelf_summary in shelf_summaries:
                    # The shelves endpoint does not provide book/chapter/page counts, so we need to fetch the details of each shelf to 
                    # get its books, and then for each book, we need to fetch its contents to count chapters and pages. 
                    shelf_detail = await get_json(f"shelves/{shelf_summary['id']}")
                    books = shelf_detail.get("books", [])

                    chapter_count = 0
                    page_count = 0
                    for book in books:
                        # Fetch the book's content which lists all of the chapters and top-level pages within the book.
                        book_detail = await get_json(f"books/{book['id']}")
                        # Firstly count the top-level chapters and pages directly under the book.
                        for item in book_detail.get("contents", []):
                            if item.get("type") == "chapter":
                                chapter_count += 1
                            elif item.get("type") == "page":
                                page_count += 1
                        # Then we need to loop through the chapters to count the pages within them.
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

            # If all API calls were successful, we can mark the coordinator as available.
            self.is_available = True
            # Log when the API comes back online after being unavailable.
            if self._was_available is False:
                _LOGGER.info("BookStack at %s is back online", base_url)
            self._was_available = True
            # Return all of the data as coordinator.data, which will be available to the sensors to access via self.coordinator.data.
            return data

        except ConfigEntryAuthFailed:
            # If we get an authentication error, we mark the coordinator as unavailable and HA will show a repair notification. Also 
            # don't keep retrying to connect until the user fixes the credentials.
            self.is_available = False
            self._was_available = False
            raise
        except aiohttp.ClientError as err:
            # If we get a network error (e.g., connection refused, DNS failure), we mark the coordinator as unavailable but keep 
            # retrying in case the connection is temporary.
            self.is_available = False
            # Log once when connection is lost.
            if self._was_available is not False:
                _LOGGER.warning(
                    "BookStack at %s is unavailable: %s", base_url, err
                )
            self._was_available = False
            # Wrap the original exception in an UpdateFailed to signal to the DataUpdateCoordinator that the update failed due to a 
            # connection issue. This will trigger the retry logic based on the update interval.
            raise UpdateFailed(f"Connection error: {err}") from err