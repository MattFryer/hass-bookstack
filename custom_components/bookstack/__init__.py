"""BookStack integration for Home Assistant.

This integration connects Home Assistant to a BookStack instance, allowing you to monitor various metrics such as the number of books, 
chapters, pages, users, and images in your BookStack library. It also provides optional sensors for each shelf in BookStack if enabled.

This is the integrations main entry point, where we set up the integration, handle configuration entries, and manage the lifecycle of 
the coordinator and entities. The functions defined here are:

- async_setup_entry: Called when the user adds BookStack (or HA restores it on startup). Creates the data coordinator and initialises 
    all sensor platforms.
- _async_update_listener: Called when the user updates options. Triggers a reload of the config entry to apply changes.
- async_unload_entry: Called when the user removes the integration. Unloads all platforms and allows HA to clean up the coordinator and 
    entities.

High-level architecture: Config Entry → BookStackCoordinator (polls API) → Sensor entities (read data returned from API)                            
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, PLATFORMS, CONF_SCAN_INTERVAL, CONF_PER_SHELF_ENABLED, DEFAULT_SCAN_INTERVAL
from .coordinator import BookStackCoordinator

# Set up logging for the integration. This allows us to log important information and errors, which can be helpful for debugging and 
# monitoring the integration. Using __name__ produces "custom_components.bookstack" which makes log entries easy to filter in the HA 
# log viewer.
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BookStack from a config entry.
    
    Called by HA when the user adds the integration (or HA restores it on startup). We create the data coordinator here, which will 
    manage polling the BookStack API and providing data to sensor entities. We also set up the sensor platforms, which will create the 
    individual sensor entities.
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