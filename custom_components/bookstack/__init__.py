from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, PLATFORMS, CONF_SCAN_INTERVAL, CONF_PER_SHELF_ENABLED, DEFAULT_SCAN_INTERVAL
from .coordinator import BookStackCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BookStack from a config entry."""
    session = async_get_clientsession(hass)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    per_shelf_enabled = entry.options.get(CONF_PER_SHELF_ENABLED, True)

    coordinator = BookStackCoordinator(
        hass, session, entry.data, scan_interval, per_shelf_enabled
    )
    await coordinator.async_config_entry_first_refresh()

    # Silver: runtime-data — store coordinator on entry.runtime_data instead of
    # hass.data so HA can manage its lifecycle and it's accessible via the entry.
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates by reloading the config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload BookStack entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)