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
        → BookStackCoordinator (polls API and exposed write methods) 
            → Sensor entities (read data returned from API) 
            → HA Actions (call coordinator methods to perform actions like creating a book)                                                          
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN, 
    PLATFORMS, 
    CONF_SCAN_INTERVAL, 
    CONF_PER_SHELF_ENABLED, 
    DEFAULT_SCAN_INTERVAL,
    ACTION_CREATE_BOOK,
    ACTION_CREATE_PAGE,
    ACTION_APPEND_PAGE,
)
from .coordinator import BookStackCoordinator

# Set up logging for the integration. This allows us to log important information and errors, which can be helpful for debugging and 
# monitoring the integration. Using __name__ produces "custom_components.bookstack" which makes log entries easy to filter in the HA 
# log viewer.
_LOGGER = logging.getLogger(__name__)


# Voluptuous schema that validates the data payload when the create_book action is called (from the UI, an automation, or a script). 
# HA validates this before  our handler runs, so we can trust the types and required fields are present.
# Field notes:
#   shelf_id    — 
#   name        — non-empty string; cv.string also strips leading/trailing whitespace
#   description — optional, defaults to an empty string
#   tags        — optional list of tag dicts with required "name" and optional "value"; defaults to an empty list
CREATE_BOOK_SCHEMA = vol.Schema(
    {
        vol.Required("shelf_id"): vol.All(int, vol.Range(min=1)), # must be a positive integer (BookStack IDs start at 1)
        vol.Required("name"): cv.string, # non-empty string; cv.string also strips leading/trailing whitespace
        vol.Optional("description", default=""): cv.string, # optional, defaults to an empty string
        vol.Optional("tags", default=[]): [
            vol.Schema(
                {
                    vol.Required("name"): cv.string,
                    vol.Optional("value", default=""): cv.string,
                }
            )
        ],
    }
)

# Voluptuous schema that validates the data payload when the create_page action is called. Both html and markdown are 
# optional at the schema level — the coordinator enforces that exactly one must be supplied, since Voluptuous cannot 
# handle mutual exclusivity.
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
        vol.Required("name"): cv.string,
        vol.Optional("html"): cv.string,
        vol.Optional("markdown"): cv.string,
        vol.Optional("tags", default=[]): [
            vol.Schema(
                {
                    vol.Required("name"): cv.string,
                    vol.Optional("value", default=""): cv.string,
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
        vol.Optional("html"): cv.string,
        vol.Optional("markdown"): cv.string,
        vol.Optional("tags", default=[]): [
            vol.Schema(
                {
                    vol.Required("name"): cv.string,
                    vol.Optional("value", default=""): cv.string,
                }
            )
        ],
    }
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BookStack from a config entry.
    
    Called by HA when the user adds the integration (or HA restores it on startup). We create the data coordinator here, which will 
    manage polling the BookStack API and providing data to sensor entities. We also set up the sensor platforms, which will create the 
    individual sensor entities, and register any integration actions.
    """

    # Use HA's aiohttp client session for making HTTP requests to the BookStack API. This ensures that we reuse connections and 
    # integrate with HA's session management.
    session = async_get_clientsession(hass)

    # Read options from the config entry, using defaults if not set. These options can be updated by the user through the options flow, 
    # and we'll handle that by reloading the config entry when options change.
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    per_shelf_enabled = entry.options.get(CONF_PER_SHELF_ENABLED, True)

    # Instantiate the coordinator, which will handle fetching data from the BookStack API and updating entities. We pass in the necessary
    # parameters, including the HA instance, HTTP session, config entry data (which contains authentication info), and options returned
    # above.
    coordinator = BookStackCoordinator(
        hass, session, entry.data, scan_interval, per_shelf_enabled
    )
    await coordinator.async_config_entry_first_refresh()

    # Attach the coordinator to the config entry's runtime_data so that we can access it from sensor entities later. This is a common 
    # pattern in HA integrations for sharing the coordinator instance across platforms and entities.
    entry.runtime_data = coordinator

    # Set up each of the platforms in the const.py platform list. This will trigger HA to call the async_setup_entry function in each 
    # platform's module (e.g., sensor.py), where we will create the individual sensor entities.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register integration actions (formerly known as services). This allows users to call these actions from the HA Developer Tools, 
    # UI, automations, or scripts.

    # We check has_service before registering to avoid duplicate registration warnings if multiple BookStack config entries exist.
    # The handler looks up the correct coordinator via the config entry so each BookStack instance is targeted independently.
    if not hass.services.has_service(DOMAIN, ACTION_CREATE_BOOK):

        async def handle_create_book(call: ServiceCall) -> None:
            """Handle the bookstack.create_book action call.

            Looks up the coordinator for the target config entry, validates that BookStack is reachable, then delegates to the 
            coordinator's async_create_book method.

            The action response (the new book's full API data) is returned to the caller so it can be used in automation templates, 
            e.g.: response = action bookstack.create_book ...
                  book_id: "{{ response.id }}"
            """
            # If the user has multiple BookStack entries, the action call should # include a config_entry_id to target the right one. We 
            # fall back to this entry's ID when there is only one instance.
            target_entry_id = call.data.get("config_entry_id", entry.entry_id)
            target_entry = hass.config_entries.async_get_entry(target_entry_id)

            if target_entry is None:
                raise ServiceValidationError(
                    f"No BookStack config entry found with ID '{target_entry_id}'"
                )

            target_coordinator: BookStackCoordinator = target_entry.runtime_data

            # Prevent from calling the API when BookStack is known to be offline, giving the user a clear error rather than a confusing 
            # timeout.
            if not target_coordinator.is_available:
                raise ServiceValidationError(
                    "BookStack is currently unavailable. Check the Connectivity "
                    "sensor and your BookStack server before retrying."
                )

            # Delegate to the coordinator method which handles the API calls. async_create_book raises ServiceValidationError or 
            # HomeAssistantError on failure, both of which HA surfaces to the caller automatically.
            return await target_coordinator.async_create_book(
                shelf_id=call.data["shelf_id"],
                name=call.data["name"],
                description=call.data.get("description", ""),
                tags=call.data.get("tags", []),
            )

        hass.services.async_register(
            domain=DOMAIN,
            service=ACTION_CREATE_BOOK,
            service_func=handle_create_book,
            schema=CREATE_BOOK_SCHEMA,
            # supports_response tells HA that this action returns data, making it available as a response variable in automations and 
            # scripts.
            supports_response=SupportsResponse.OPTIONAL,
        )

        # Unregister the action cleanly when the entry is unloaded. Without this, reloading the integration would try to register it a 
        # second time and log a warning.
        entry.async_on_unload(
            lambda: hass.services.async_remove(DOMAIN, ACTION_CREATE_BOOK)
        )

    if not hass.services.has_service(DOMAIN, ACTION_CREATE_PAGE):

        async def handle_create_page(call: ServiceCall) -> None:
            """Handle the bookstack.create_page action call.

            Looks up the coordinator for the target config entry, validates that BookStack is reachable, then delegates to the 
            coordinator's async_create_page method.

            The action response (the new page's full API data) is returned to the caller so it can be used in automation templates, 
            e.g.:
                response = action bookstack.create_page ...
                page_id: "{{ response.id }}"
            """
            target_entry_id = call.data.get("config_entry_id", entry.entry_id)
            target_entry = hass.config_entries.async_get_entry(target_entry_id)

            if target_entry is None:
                raise ServiceValidationError(
                    f"No BookStack config entry found with ID '{target_entry_id}'"
                )

            target_coordinator: BookStackCoordinator = target_entry.runtime_data

            if not target_coordinator.is_available:
                raise ServiceValidationError(
                    "BookStack is currently unavailable. Check the Connectivity sensor and your BookStack server before retrying."
                )

            return await target_coordinator.async_create_page(
                book_id=call.data["book_id"],
                name=call.data["name"],
                chapter_id=call.data.get("chapter_id"),
                html=call.data.get("html"),
                markdown=call.data.get("markdown"),
                tags=call.data.get("tags", []),
            )

        hass.services.async_register(
            domain=DOMAIN,
            service=ACTION_CREATE_PAGE,
            service_func=handle_create_page,
            schema=CREATE_PAGE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

        entry.async_on_unload(
            lambda: hass.services.async_remove(DOMAIN, ACTION_CREATE_PAGE)
        )

    if not hass.services.has_service(DOMAIN, ACTION_APPEND_PAGE):

        async def handle_append_page(call: ServiceCall) -> None:
            """Handle the bookstack.append_page action call.

            Looks up the coordinator for the target config entry, validates that BookStack is reachable, then delegates to the 
            coordinator's async_append_page method.

            The action response (the updated page's full API data) is returned to the caller so it
            can be used in automation templates, e.g.:
                response = action bookstack.append_page ...
                updated_at: "{{ response.updated_at }}"
            """
            target_entry_id = call.data.get("config_entry_id", entry.entry_id)
            target_entry = hass.config_entries.async_get_entry(target_entry_id)

            if target_entry is None:
                raise ServiceValidationError(
                    f"No BookStack config entry found with ID '{target_entry_id}'"
                )

            target_coordinator: BookStackCoordinator = target_entry.runtime_data

            if not target_coordinator.is_available:
                raise ServiceValidationError(
                    "BookStack is currently unavailable. Check the Connectivity sensor and your BookStack server before retrying."
                )

            return await target_coordinator.async_append_page(
                page_id=call.data["page_id"],
                html=call.data.get("html"),
                markdown=call.data.get("markdown"),
                tags=call.data.get("tags", []),
            )

        hass.services.async_register(
            domain=DOMAIN,
            service=ACTION_APPEND_PAGE,
            service_func=handle_append_page,
            schema=APPEND_PAGE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

        entry.async_on_unload(
            lambda: hass.services.async_remove(DOMAIN, ACTION_APPEND_PAGE)
        )

    # Set up an update listener for the config entry. This will call the _async_update_listener function whenever the user updates 
    # options, allowing us to reload the config entry and apply changes without needing to restart HA.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates by reloading the config entry.
    
    This is called automatically by HA when the user updates options through the UI. We simply trigger a reload of the config entry, 
    which will cause the integration to be reloaded with the new options.
    """
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload BookStack entry.
    
    This is called by HA when the user removes the integration. We need to unload all platforms to allow HA to clean up the coordinator 
    and entities.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)