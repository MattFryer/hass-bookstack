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
    """Coordinator to handle all communication with the BookStack API including:
        - Getting BookStack stats and per-shelf book counts at the desired interval.
        - Handling actions (services) that perform API calls to modify data in BookStack, such as creating a new book.
    
    Inherits the HA DataUpdateCoordinator, which provides a convenient way to manage periodic data fetching and updating entities. We 
    implement the _async_update_data method to fetch data from the BookStack API, and we can call self.async_refresh() to trigger an 
    update when options change.

    We also implement an async_create_book method that can be called by the service handler when the "create_book" action is invoked. 
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
        
    async def async_create_book(
        self,
        shelf_id: int,
        name: str,
        description: str = "",
        tags: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Create a new book on the specified shelf via the BookStack API.

        Calls POST /api/books to create the book (with name, description, and tags). The API doesn't allow us to specify the shelf when 
        creating the book, so we then call PUT /api/shelves/{shelf_id} to assign it to the shelf.

        Arguments:
            shelf_id:       The BookStack ID of the shelf the book should live on.
            name:           The display name of the new book (required by the API).
            description:    Optional plain-text description shown on the book cover.
            tags:           Optional list of tag dicts to attach to the book. Each dict must have a required "name" key and an optional 
                            "value" key (e.g. [{"name": "env", "value": "prod"}, {"name": "draft"}]). Omitting "value" (or leaving it blank) 
                            displays the tag as a label-style tag in the BookStack UI.

        Returns:
            The full book object returned by the BookStack API (includes the new book's id, slug, url, created_at, etc.).

        Raises:
            ServiceValidationError: if the request is rejected by the API (e.g.
                                    blank name, shelf not found).
            HomeAssistantError:     on unexpected API errors or network failures.
        """
        # Import here to keep the top-level imports as minimal as possible. These are only needed when an action is called, not during 
        # normal coordinator polling.
        from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

        headers = {
            "Authorization": f"Token {self.config['token_id']}:{self.config['token_secret']}", # Define the auth header as normal
            "Content-Type": "application/json", # We're sending JSON bodies, so tell the API what to expect.
        }
        base_url = self.config["url"].rstrip("/") # Get the BookStack base URL from the config and make sure it doesn't end with a slash.
        timeout = aiohttp.ClientTimeout(total=10) # Set a reasonable timeout for the API requests.

        # Step 1: Create the book with the provided name, description, and tags. The API requires at least a name, but description and 
        # tags are optional. 

        # Convert the list of tag dicts into the format the BookStack API expects: 
        #   [{"name": "tag1", "value": "val1"}, {"name": "tag2", "value": ""}, ...].
        # Stripping whitespace from names avoids accidentally creating blank tags. The "value" key is included even when empty, which is 
        # valid in the BookStack API and displays the tag as a label-style tag (name only) in the BookStack UI.
        tag_payload = [
            {"name": t["name"].strip(), "value": t.get("value", "").strip()}
            for t in (tags or [])
            if t.get("name", "").strip()
        ]

        book_payload: dict[str, Any] = {
            "name": name,
            "description": description,
            "tags": tag_payload,
        }

        books_url = f"{base_url}/api/books" # Set the endpoint for creating the book
        try:
            async with self.session.post(
                books_url, headers=headers, json=book_payload, timeout=timeout
            ) as resp:
                if resp.status == 401:
                    raise HomeAssistantError(
                        "BookStack rejected the request: invalid API credentials"
                    )
                if resp.status == 422:
                    # Unprocessable Entity — the API rejected the payload (e.g. name is blank). Include the response body for context.
                    body = await resp.text()
                    raise ServiceValidationError(
                        f"BookStack rejected the book data: {body}"
                    )
                if resp.status != 200:
                    # For any other unexpected status code, raise a generic error with the status code. 
                    raise HomeAssistantError(
                        f"Unexpected response from BookStack when creating book "
                        f"(HTTP {resp.status})"
                    )
                # For a successful creation, the API returns the full book object in the response body, which includes the new book's 
                # ID, slug, URL, etc. We return this to the caller so they can use that information in their automation templates if 
                # needed.
                book = await resp.json() 

        except (HomeAssistantError, ServiceValidationError):
            raise  # Re-raise our own errors unchanged
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Could not connect to BookStack to create book: {err}"
            ) from err

        # Step 2: Assign the book to the requested shelf

        # To place a book on a shelf we must PUT the shelf with its complete current book list plus the new book's ID. We fetch the 
        # shelf first so we don't accidentally remove books that are already on it.

        shelf_url = f"{base_url}/api/shelves/{shelf_id}" # Endpoint for fetching and updating the shelf.
        try:
            async with self.session.get(
                shelf_url, headers=headers, timeout=timeout
            ) as resp:
                if resp.status == 404:
                    # If the shelf doesn't exist, log the orphaned book ID so the user can find and clean it up.
                    _LOGGER.warning(
                        "Book '%s' (id=%s) was created but shelf %s was not found. "
                        "The book exists in BookStack but is not on any shelf.",
                        name, book.get("id"), shelf_id,
                    )
                    # Return an error back to the user so they also know that the shelf wasn't found.
                    raise ServiceValidationError(
                        f"Shelf with ID {shelf_id} was not found. The book was "
                        f"created (id={book.get('id')}) but could not be assigned "
                        f"to the shelf."
                    )
                if resp.status != 200:
                    # If we get any other error, raise a generic error with the status code. Again, the book will have been created but 
                    # not assigned to the shelf.
                    raise HomeAssistantError(
                        f"Unexpected response fetching shelf {shelf_id} "
                        f"(HTTP {resp.status})"
                    )
                shelf_data = await resp.json()

        except (HomeAssistantError, ServiceValidationError):
            raise # Re-raise our own errors unchanged
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Could not connect to BookStack to fetch shelf: {err}"
            ) from err

        # Build the updated list of book IDs adding the new book ID to those already on the shelf.
        existing_book_ids = [b["id"] for b in shelf_data.get("books", [])]
        updated_book_ids = existing_book_ids + [book["id"]]

        shelf_payload = {"books": updated_book_ids} # Create the JSON payload to update the shelf with the new list of books.

        # Make the PUT request to update the shelf
        try:
            async with self.session.put(
                shelf_url, headers=headers, json=shelf_payload, timeout=timeout
            ) as resp:
                if resp.status not in (200, 204):
                    # If we don't get a success status code, raise an error. The book will have been created but not assigned to the 
                    # shelf as intended.
                    raise HomeAssistantError(
                        f"Unexpected response assigning book to shelf "
                        f"(HTTP {resp.status})"
                    )

        except (HomeAssistantError, ServiceValidationError):
            raise # Re-raise our own errors unchanged
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Could not connect to BookStack to update shelf: {err}"
            ) from err

        _LOGGER.debug(
            "Created book '%s' (id=%s) on shelf %s", name, book.get("id"), shelf_id
        )

        # Trigger an immediate coordinator refresh so the book-count sensors update straight away rather than waiting for the next 
        # scheduled poll.
        await self.async_request_refresh()

        # Return the info about the newly created book to the caller (e.g. book ID, slug, url, etc), which can be used in the automation 
        # response or templates.
        return book
    
    async def async_create_page(
        self,
        book_id: int,
        name: str,
        chapter_id: int | None = None,
        html: str | None = None,
        markdown: str | None = None,
        tags: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Create a new page in the specified book (and optionally chapter) via the BookStack API.

        Calls POST /api/pages to create the page. Exactly one of html or markdown must be provided. Supplying both or neither raises a 
        ServiceValidationError before any API call is made.

        Arguments:
            book_id:    The BookStack ID of the book the page should be created in.
            name:       The display name (title) of the new page (required by the API).
            chapter_id: Optional BookStack ID of a chapter within the book. When provided the page is nested inside that chapter; when 
                        omitted the page sits at the top level of the book.
            html:       Page content as an HTML string. Mutually exclusive with markdown.
            markdown:   Page content as a Markdown string. Mutually exclusive with html.
            tags:       Optional list of tag dicts to attach to the page. Each dict must have a required "name" key and an optional 
                        "value" key (e.g. [{"name": "env", "value": "prod"}, {"name": "draft"}]). Omitting "value" (or leaving it blank) 
                        displays the tag as a plain label.

        Returns:
            The full page object returned by the BookStack API (includes the new page's id, slug, url, book_id, chapter_id, created_at, etc.).

        Raises:
            ServiceValidationError: if neither or both of html/markdown are supplied, or if the
                                    API rejects the request (e.g. blank name, book not found).
            HomeAssistantError:     on unexpected API errors or network failures.
        """
        from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

        # Validate the html/markdown mutual exclusivity before making any API calls so the user gets a clear error message rather than a 
        # confusing API response.
        has_html = html is not None and html.strip() != ""
        has_markdown = markdown is not None and markdown.strip() != ""

        if has_html and has_markdown:
            raise ServiceValidationError(
                "Provide either 'html' or 'markdown' for the page content, not both."
            )
        if not has_html and not has_markdown:
            raise ServiceValidationError(
                "Either 'html' or 'markdown' must be provided for the page content."
            )

        headers = {
            "Authorization": f"Token {self.config['token_id']}:{self.config['token_secret']}",
            "Content-Type": "application/json",
        }
        base_url = self.config["url"].rstrip("/")
        timeout = aiohttp.ClientTimeout(total=10)

        # Build the tag payload in the format the BookStack API expects. Tags with an empty value are included as-is. The API treats 
        # them as label-style tags.
        tag_payload = [
            {"name": t["name"].strip(), "value": t.get("value", "").strip()}
            for t in (tags or [])
            if t.get("name", "").strip()
        ]

        # Build the page payload. We always send book_id; chapter_id is only included when provided since sending null/None would be 
        # treated as "no chapter" by the API anyway, but omitting it entirely is cleaner and avoids potential API validation issues.
        page_payload: dict[str, Any] = {
            "book_id": book_id,
            "name": name,
            "tags": tag_payload,
        }

        if chapter_id is not None:
            # When a chapter_id is given the API also requires book_id (already set above). The page will appear inside the chapter 
            # rather than at the top level of the book.
            page_payload["chapter_id"] = chapter_id

        # Add the content under the correct key depending on which format was supplied.
        if has_html:
            page_payload["html"] = html
        else:
            page_payload["markdown"] = markdown

        pages_url = f"{base_url}/api/pages"
        try:
            async with self.session.post(
                pages_url, headers=headers, json=page_payload, timeout=timeout
            ) as resp:
                if resp.status == 401:
                    raise HomeAssistantError(
                        "BookStack rejected the request: invalid API credentials"
                    )
                if resp.status == 422:
                    # Unprocessable Entity — the API rejected the payload (e.g. blank name, book_id not found). Include the response body 
                    # for context.
                    body = await resp.text()
                    raise ServiceValidationError(
                        f"BookStack rejected the page data: {body}"
                    )
                if resp.status != 200:
                    raise HomeAssistantError(
                        f"Unexpected response from BookStack when creating page "
                        f"(HTTP {resp.status})"
                    )
                page = await resp.json()

        except (HomeAssistantError, ServiceValidationError):
            raise
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Could not connect to BookStack to create page: {err}"
            ) from err

        _LOGGER.debug(
            "Created page '%s' (id=%s) in book %s%s",
            name,
            page.get("id"),
            book_id,
            f", chapter {chapter_id}" if chapter_id is not None else "",
        )

        # Trigger a coordinator refresh so the page-count sensors update straight away.
        await self.async_request_refresh()

        # Return the full page object to the caller so they can use the page ID, slug, URL etc. in automation response templates.
        return page
    
    async def async_append_page(
        self,
        page_id: int,
        html: str | None = None,
        markdown: str | None = None,
        tags: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Append content to an existing page via the BookStack API.

        Fetches the current page (GET /api/pages/{id}), validates that the supplied content format matches the page's existing format, 
        merges the new content onto the end, then writes it back (PUT /api/pages/{id}).

        A page is considered Markdown-mode when its ``markdown`` field returned by the API is non-empty; otherwise it is treated as 
        HTML-mode. Attempting to append HTML to a Markdown page (or vice-versa) raises a ServiceValidationError before any write is 
        attempted.

        Any tags supplied are *added* to the page. Existing tags on the page are preserved; the combined list (existing + new) is sent in
        the PUT payload. Duplicate tag name/value pairs are de-duplicated so that calling the action repeatedly does not accumulate 
        identical tags.

        Arguments:
            page_id:    The BookStack ID of the page to append content to.
            html:       Content to append as an HTML string. Mutually exclusive with markdown.
            markdown:   Content to append as a Markdown string. Mutually exclusive with html.
            tags:       Optional list of tag dicts to add to the page. Each dict must have a required "name" key and an optional "value" 
                        key. Existing tags are preserved.

        Returns:
            The full updated page object returned by the BookStack API.

        Raises:
            ServiceValidationError: if neither or both of html/markdown are supplied, if the formats are mismatched, or if the page is 
            not found (404).
            HomeAssistantError:     on unexpected API errors or network failures.
        """
        from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

        # Validate the html/markdown mutual exclusivity before touching the API.
        has_html = html is not None and html.strip() != ""
        has_markdown = markdown is not None and markdown.strip() != ""

        if has_html and has_markdown:
            raise ServiceValidationError(
                "Provide either 'html' or 'markdown' for the content to append, not both."
            )
        if not has_html and not has_markdown:
            raise ServiceValidationError(
                "Either 'html' or 'markdown' must be provided for the content to append."
            )

        headers = {
            "Authorization": f"Token {self.config['token_id']}:{self.config['token_secret']}",
            "Content-Type": "application/json",
        }
        base_url = self.config["url"].rstrip("/")
        timeout = aiohttp.ClientTimeout(total=10)
        page_url = f"{base_url}/api/pages/{page_id}"

        # Step 1: Fetch the existing page so we can read its current content and tags.
        try:
            async with self.session.get(page_url, headers=headers, timeout=timeout) as resp:
                if resp.status == 404:
                    raise ServiceValidationError(
                        f"Page with ID {page_id} was not found in BookStack."
                    )
                if resp.status == 401:
                    raise HomeAssistantError(
                        "BookStack rejected the request: invalid API credentials"
                    )
                if resp.status != 200:
                    raise HomeAssistantError(
                        f"Unexpected response fetching page {page_id} (HTTP {resp.status})"
                    )
                existing = await resp.json()

        except (HomeAssistantError, ServiceValidationError):
            raise
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Could not connect to BookStack to fetch page {page_id}: {err}"
            ) from err

        # Step 2: Determine whether the existing page is Markdown-mode or HTML-mode. The API always returns both fields, but markdown 
        # will be an empty string for HTML pages.
        existing_markdown = existing.get("markdown", "")
        page_is_markdown = bool(existing_markdown)  # non-empty string → Markdown page

        if page_is_markdown and has_html:
            raise ServiceValidationError(
                f"Page {page_id} uses Markdown. Provide 'markdown' content to append, not 'html'."
            )
        if not page_is_markdown and has_markdown:
            raise ServiceValidationError(
                f"Page {page_id} uses HTML. Provide 'html' content to append, not 'markdown'."
            )

        # Step 3: Build the merged content by appending the new content to the existing content.
        if page_is_markdown:
            # For Markdown pages we separate the existing and new content with a blank line, which is the standard Markdown paragraph 
            # separator and avoids unintentionally merging the last line of the existing content with the first line of the new content.
            merged_content_key = "markdown"
            merged_content_value = existing_markdown.rstrip("\n") + "\n\n" + markdown.strip()
        else:
            # For HTML pages we simply concatenate the existing and new HTML. BookStack stores page content as a sequence of block-level
            # elements, so concatenation is safe as long as the supplied html contains valid block-level elements (as the API docs 
            # recommend).
            merged_content_key = "html"
            merged_content_value = existing.get("html", "") + html

        # Step 4: Merge the tags. Preserve all existing tags and add any new ones that are not already present (matched on both name and 
        # value to avoid exact duplicates).
        new_tag_payload = [
            {"name": t["name"].strip(), "value": t.get("value", "").strip()}
            for t in (tags or [])
            if t.get("name", "").strip()
        ]
        # Start with the existing tags
        existing_tags = existing.get("tags", [])

        # Normalise existing tags to the same name/value dict structure the API accepts on write, dropping any extra fields (e.g. 
        # "order") that the read response may include.
        existing_tag_payload = [
            {"name": t["name"], "value": t.get("value", "")}
            for t in existing_tags
        ]

        # De-duplicate tags: only add new tags whose (name, value) pair isn't already present.
        existing_tag_set = {(t["name"], t["value"]) for t in existing_tag_payload}
        merged_tags = existing_tag_payload + [
            t for t in new_tag_payload
            if (t["name"], t["value"]) not in existing_tag_set
        ]

        # Step 5: Write the updated page back to BookStack.
        put_payload: dict[str, Any] = {
            merged_content_key: merged_content_value,
            "tags": merged_tags,
        }

        # Handle the outcome of writing the new version of the page back to the API.
        try:
            async with self.session.put(
                page_url, headers=headers, json=put_payload, timeout=timeout
            ) as resp:
                if resp.status == 401:
                    raise HomeAssistantError(
                        "BookStack rejected the request: invalid API credentials"
                    )
                if resp.status == 422:
                    body = await resp.text()
                    raise ServiceValidationError(
                        f"BookStack rejected the updated page data: {body}"
                    )
                if resp.status != 200:
                    raise HomeAssistantError(
                        f"Unexpected response from BookStack when updating page {page_id} "
                        f"(HTTP {resp.status})"
                    )
                updated_page = await resp.json()

        except (HomeAssistantError, ServiceValidationError):
            raise # Re-raise our own errors unchanged
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"Could not connect to BookStack to update page {page_id}: {err}"
            ) from err

        _LOGGER.debug("Appended content to page '%s' (id=%s)", updated_page.get("name"), page_id)

        # We don't need to trigger a coordinator refresh as updating the contents of a single page won't cause any sensor counts to 
        # change.  Instead we just return the updated page data to the caller so we can use it in our automation response/templates 
        # if needed.
        return updated_page