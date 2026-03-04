"""BookStack integration for Home Assistant.

This integration connects Home Assistant to a BookStack instance, allowing you to monitor various metrics such as the number of books, 
chapters, pages, users, and images in your BookStack library. It also provides optional sensors for each shelf in BookStack if enabled.

This is the integrations main entry point, where we set up the integration, handle configuration entries, and manage the lifecycle of 
the coordinator and entities. The functions defined here are:

- async_setup_entry: Called when the user adds BookStack (or HA restores it on startup). Creates the data coordinator and initialises 
    all sensor platforms, and registers integration actions (formerly known as services).
- _async_update_listener: Called when the user updates options. Triggers a reload of the config entry to apply changes.
- async_unload_entry: Called when the user removes the integration. Unloads all platforms and allows HA to clean up the coordinator and 
    entities.

High-level architecture:
    Config Entry
        -> BookStackCoordinator (polls API, exposes write methods)
            -> Sensor entities (read coordinator data)
            -> Binary sensor entities (connectivity status)
            -> HA Actions (create_book, create_page, append_page via coordinator methods)
"""

from __future__ import annotations

import logging

import voluptuous as vol # type: ignore

from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse # type: ignore
from homeassistant.exceptions import ServiceValidationError # type: ignore
from homeassistant.helpers import config_validation # type: ignore
from homeassistant.helpers.aiohttp_client import async_get_clientsession # type: ignore

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_SCAN_INTERVAL,
    CONF_PER_SHELF_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    ACTION_CREATE_BOOK,
    ACTION_CREATE_PAGE,
    ACTION_APPEND_PAGE,
    ACTION_LIST_BOOKS,
)
from .coordinator import BookStackCoordinator

CONFIG_SCHEMA = config_validation.config_entry_only_config_schema(DOMAIN)

# Set up logging for the integration. This allows us to log important information and errors, which can be helpful for debugging and 
# monitoring the integration. Using __name__ produces "custom_components.bookstack" which makes log entries easy to filter in the HA 
# log viewer.
_LOGGER = logging.getLogger(__name__)


# Voluptuous schema that validates the data payload when the create_book action is called (from the UI, an automation, or a script). 
# HA validates this before  our handler runs, so we can trust the types and required fields are present.
# Field notes:
#   shelf_id    — 
#   name        — non-empty string; config_validation.string also strips leading/trailing whitespace
#   description — optional, defaults to an empty string
#   tags        — optional list of tag dicts with required "name" and optional "value"; defaults to an empty list
CREATE_BOOK_SCHEMA = vol.Schema(
    {
        vol.Required("shelf_id"): vol.All(int, vol.Range(min=1)), # must be a positive integer (BookStack IDs start at 1)
        vol.Required("name"): config_validation.string, # non-empty string; config_validation.string also strips leading/trailing whitespace
        vol.Optional("description", default=""): config_validation.string, # optional, defaults to an empty string
        vol.Optional("tags", default=[]): [
            vol.Schema(
                {
                    vol.Required("name"): config_validation.string,
                    vol.Optional("value", default=""): config_validation.string,
                }
            )
        ],
    }
)

# Voluptuous schema that validates the data payload when the create_page action is called. Both html and markdown are optional at the schema 
# level — the coordinator enforces that exactly one must be supplied, since Voluptuous cannot handle mutual exclusivity.
# Field notes:
#   book_id    — required; the book the page will be created in
#   chapter_id — optional; if supplied the page is nested inside that chapter
#   name       — non-empty string; the page title
#   html       — page content as HTML; mutually exclusive with markdown
#   markdown   — page content as Markdown; mutually exclusive with html
#   tags       — optional list of tag dicts with required "name" and optional "value"
CREATE_PAGE_SCHEMA = vol.Schema(
    {
        vol.Required("book_id"): vol.All(int, vol.Range(min=1)),
        vol.Optional("chapter_id"): vol.All(int, vol.Range(min=1)),
        vol.Required("name"): config_validation.string,
        vol.Optional("html"): config_validation.string,
        vol.Optional("markdown"): config_validation.string,
        vol.Optional("tags", default=[]): [
            vol.Schema(
                {
                    vol.Required("name"): config_validation.string,
                    vol.Optional("value", default=""): config_validation.string,
                }
            )
        ],
    }
)

# Voluptuous schema that validates the data payload when the append_page action is called. As with create_page, html and markdown are 
# both optional at the schema level. The coordinator enforces that exactly one must be supplied and that it matches the existing page's
# content type.
# Field notes:
#   page_id  — required; the ID of the page to append content to
#   html     — content to append as HTML; mutually exclusive with markdown
#   markdown — content to append as Markdown; mutually exclusive with html
#   tags     — optional list of tag dicts to add to the page; existing tags are preserved
APPEND_PAGE_SCHEMA = vol.Schema(
    {
        vol.Required("page_id"): vol.All(int, vol.Range(min=1)),
        vol.Optional("html"): config_validation.string,
        vol.Optional("markdown"): config_validation.string,
        vol.Optional("tags", default=[]): [
            vol.Schema(
                {
                    vol.Required("name"): config_validation.string,
                    vol.Optional("value", default=""): config_validation.string,
                }
            )
        ],
    }
)

# Voluptuous schema for the list_books action. shelf_id is entirely optional; when omitted all books are returned, when provided only 
# books on that shelf are returned.
LIST_BOOKS_SCHEMA = vol.Schema(
    {
        vol.Optional("shelf_id"): vol.All(int, vol.Range(min=1)),
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register BookStack service actions at integration load time.

    Actions are registered in async_setup (not async_setup_entry) so they are available immediately on load and never duplicated across 
    multiple config entries. Each handler resolves the correct coordinator at call-time. This satisfies the Bronze quality-scale rule 
    'action-setup'.
    """

    def _get_coordinator(call: ServiceCall) -> BookStackCoordinator:
        """Resolve and return the coordinator for the targeted config entry."""
        entries = hass.config_entries.async_entries(DOMAIN)
        target_id: str | None = call.data.get("config_entry_id")
        if target_id:
            entry = hass.config_entries.async_get_entry(target_id)
        else:
            entry = entries[0] if entries else None

        if entry is None:
            raise ServiceValidationError(
                "No BookStack config entry found"
                + (f" with ID '{target_id}'" if target_id else "")
            )

        coordinator: BookStackCoordinator = entry.runtime_data
        if not coordinator.is_available:
            raise ServiceValidationError(
                "BookStack is currently unavailable. Check the Connectivity sensor and your BookStack server before retrying."
            )
        return coordinator

    async def handle_create_book(call: ServiceCall) -> dict:
        """Handle the bookstack.create_book action."""
        coordinator = _get_coordinator(call)
        return await coordinator.async_create_book(
            shelf_id=call.data["shelf_id"],
            name=call.data["name"],
            description=call.data.get("description", ""),
            tags=call.data.get("tags", []),
        )

    async def handle_create_page(call: ServiceCall) -> dict:
        """Handle the bookstack.create_page action."""
        coordinator = _get_coordinator(call)
        return await coordinator.async_create_page(
            book_id=call.data["book_id"],
            name=call.data["name"],
            chapter_id=call.data.get("chapter_id"),
            html=call.data.get("html"),
            markdown=call.data.get("markdown"),
            tags=call.data.get("tags", []),
        )

    async def handle_append_page(call: ServiceCall) -> dict:
        """Handle the bookstack.append_page action."""
        coordinator = _get_coordinator(call)
        return await coordinator.async_append_page(
            page_id=call.data["page_id"],
            html=call.data.get("html"),
            markdown=call.data.get("markdown"),
            tags=call.data.get("tags", []),
        )

    async def handle_list_books(call: ServiceCall) -> dict:
        """Handle the bookstack.list_books action."""
        coordinator = _get_coordinator(call)
        return await coordinator.async_list_books(
            shelf_id=call.data.get("shelf_id"),
        )

    hass.services.async_register(
        domain=DOMAIN,
        service=ACTION_CREATE_BOOK,
        service_func=handle_create_book,
        schema=CREATE_BOOK_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        domain=DOMAIN,
        service=ACTION_CREATE_PAGE,
        service_func=handle_create_page,
        schema=CREATE_PAGE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        domain=DOMAIN,
        service=ACTION_APPEND_PAGE,
        service_func=handle_append_page,
        schema=APPEND_PAGE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        domain=DOMAIN,
        service=ACTION_LIST_BOOKS,
        service_func=handle_list_books,
        schema=LIST_BOOKS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a BookStack config entry.

    Creates the coordinator, performs the first refresh (raises ConfigEntryNotReady on failure), stores it on entry.runtime_data, then
    forwards platform setup to sensor.py and binary_sensor.py.
    """
    session = async_get_clientsession(hass)

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    per_shelf_enabled = entry.options.get(CONF_PER_SHELF_ENABLED, True)

    coordinator = BookStackCoordinator(
        hass, session, entry.data, scan_interval, per_shelf_enabled
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are changed by the user."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a BookStack config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
