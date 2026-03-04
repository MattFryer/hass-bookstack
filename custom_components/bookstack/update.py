"""Update entity for the BookStack integration.

Compares the version of the connected BookStack instance (returned by the /api/system endpoint and stored on the coordinator) against the 
latest release published on the BookStack GitHub repository.  The entity surfaces inside the HA Updates panel and supports:
  - Showing the installed and latest version strings.
  - Providing a "Read release announcement" link pointing directly to the GitHub release page for the latest version.

Performing the actual upgrade from within Home Assistant is not possible (BookStack must be updated on the server), so the INSTALL feature 
flag and install() method are intentionally omitted.

Skipping a release is handled natively by Home Assistant and does not require any custom logic in this integration.
"""

from __future__ import annotations

import logging

from homeassistant.components.update import (  # type: ignore
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry  # type: ignore
from homeassistant.core import HomeAssistant  # type: ignore
from homeassistant.helpers.entity import EntityCategory  # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback  # type: ignore
from homeassistant.helpers.update_coordinator import CoordinatorEntity  # type: ignore
from homeassistant.helpers.device_registry import DeviceInfo  # type: ignore

from .const import DOMAIN
from .coordinator import BookStackCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BookStack update entity for a config entry."""
    coordinator: BookStackCoordinator = entry.runtime_data
    async_add_entities([BookStackUpdateEntity(coordinator, entry)])


def _device_info(coordinator: BookStackCoordinator, entry: ConfigEntry) -> DeviceInfo:
    """Return shared DeviceInfo so this entity appears on the same device card."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"BookStack ({entry.data['url']})",
        manufacturer="BookStack",
        model="BookStack",
        sw_version=coordinator.version,
        configuration_url=entry.data["url"],
    )


class BookStackUpdateEntity(CoordinatorEntity[BookStackCoordinator], UpdateEntity):
    """Update entity that tracks available BookStack releases on GitHub.

    Installed version : coordinator.version (from /api/system).
    Latest version    : coordinator.latest_version (from GitHub releases API).
    Release URL       : coordinator.latest_release_url (GitHub release page).

    Supports RELEASE_NOTES to populate the "Read release announcement" link in HA's update dialog.

    INSTALL is intentionally absent — BookStack cannot be upgraded from within Home Assistant; it must be updated on the server.

    Skipping a release is handled natively by Home Assistant and requires no custom logic here.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "bookstack_update"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = UpdateEntityFeature.RELEASE_NOTES
    _attr_in_progress = False

    def __init__(
        self,
        coordinator: BookStackCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the update entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_update"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def installed_version(self) -> str | None:
        """Return the version currently running on the BookStack server."""
        return self.coordinator.version

    @property
    def latest_version(self) -> str | None:
        """Return the latest version available on GitHub.

        Returns None while the GitHub check is still pending, which causes HA to render the entity state as 'unknown'.
        """
        return self.coordinator.latest_version

    @property
    def release_url(self) -> str | None:
        """Return the GitHub release page URL for the latest version.

        HA renders this as the "Read release announcement" link inside the update dialog.
        """
        return self.coordinator.latest_release_url

    async def async_release_notes(self) -> str | None:
        """Return a brief description shown in the update dialog."""
        latest = self.coordinator.latest_version
        if not latest:
            return None
        url = self.coordinator.latest_release_url
        if url:
            return (
                f"BookStack {latest} is available.\n\n"
                f"See the full changelog and upgrade instructions on the GitHub release page:\n{url}"
            )
        return f"BookStack {latest} is available on GitHub."
