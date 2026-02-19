"""Diagnostics support for BookStack integration

HA's diagnostic feature lets users download a JSON file containing information about an integration's configuration and runtime data, 
which can be helpful for debugging issues. Users can access this from the HA UI on the config entry page for the integration. 

In this file, we implement the async_get_config_entry_diagnostics function, which gathers relevant information about the BookStack 
integration, such as the config entry data (with sensitive authentication credentials redacted), current options, and the latest data 
fetched from the API. 
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

# Define which keys in the config entry data and options should be redacted in the diagnostics output to protect sensitive information.
# They are replaced with "**REDACTED**" in the diagnostics JSON file.
REDACT_KEYS = {"token_id", "token_secret"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry
    
    This function is called by HA when the user requests diagnostics for a config entry.
    """
    # Retrieve the coordinator from the config entry's runtime_data. The coordinator contains the latest data fetched from the 
    # BookStack API, as well as the system and shelves data. We include this in the diagnostics output so that we can see what data 
    # the integration is working with, which can be helpful for debugging issues with data fetching or parsing.
    coordinator = entry.runtime_data

    return {
        "entry_data": async_redact_data(dict(entry.data), REDACT_KEYS), # Stored config entry data with sensitive info redacted.
        "entry_options": async_redact_data(dict(entry.options), REDACT_KEYS), # Stored config entry options with sensitive info redacted.
        "scan_interval_seconds": coordinator.update_interval.total_seconds() if coordinator else None, # Current scan interval in seconds.
        "system": coordinator.system_data if coordinator else {}, # Latest system data fetched from the BookStack API, which includes overall counts of shelves, books, chapters, pages, users, images, and attachments.
        "shelves": coordinator.shelves_data if coordinator else [], # Latest shelves data fetched from the BookStack API, which includes details of each shelf and its book/chapter/page counts if per-shelf sensors are enabled.
    }