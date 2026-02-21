"""Binary sensor entities for the BookStack integration.

This module defines the binary sensor entities exposed by the integration. Currently this consists solely of the connectivity sensor 
which indicates whether the BookStack instance is reachable. It reads data from the BookStackCoordinator, which is responsible for
fetching data from the BookStack API.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import BookStackCoordinator

# Limit entity updates to one at a time.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BookStack binary sensors for a config entry.

    Called by HA when the \"binary_sensor\" platform is being set up for this integration. We create the connectivity binary sensor 
    entity here.
    """
    coordinator: BookStackCoordinator = entry.runtime_data
    async_add_entities([BookStackConnectivitySensor(coordinator, entry)])


def _device_info(coordinator: BookStackCoordinator, entry: ConfigEntry) -> DeviceInfo:
    """Return shared DeviceInfo for all BookStack entities.

    All entities in this integration belong to the same device, which represents the BookStack instance. This function constructs a 
    DeviceInfo object in the HA device registry with identifiers, name, manufacturer, model, software version, and configuration URL 
    (link to the BookStack instance).
    """
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.system_data.get("instance_id", entry.entry_id))},
        name=f"BookStack ({entry.data['url']})",
        manufacturer="BookStack",
        model="BookStack",
        sw_version=coordinator.version,
        configuration_url=entry.data["url"],
    )


class BookStackConnectivitySensor(CoordinatorEntity[BookStackCoordinator], BinarySensorEntity):
    """Binary sensor indicating whether BookStack is reachable.

    Shown under the Diagnostic section of the device page. State: on = reachable, off = unreachable.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY  # Gives the sensor the correct device class in HA which affects the icon and how the values are displayed ("connected" or "disconnected")
    _attr_entity_category = EntityCategory.DIAGNOSTIC  # Causes the sensor to be shown in the "Diagnostics" section of the device page in HA
    _attr_has_entity_name = True
    _attr_icon = "mdi:close-network-outline"

    def __init__(
        self,
        coordinator: BookStackCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_name = "Connectivity"
        self._attr_unique_id = f"{entry.entry_id}_availability"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def is_on(self) -> bool:
        """Return True when BookStack was successfully reached on the last poll.

        The coordinator sets is_available=True after a successful fetch and is_available=False on any connection error or auth failure.
        """
        return self.coordinator.is_available