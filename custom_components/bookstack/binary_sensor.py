"""Binary sensor entities for the BookStack integration.

This module defines the binary sensor entities exposed by the integration. Currently this consists solely of the connectivity sensor 
which indicates whether the BookStack instance is reachable. It reads data from the BookStackCoordinator, which is responsible for
fetching data from the BookStack API.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass # type: ignore
from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.core import HomeAssistant # type: ignore
from homeassistant.helpers.entity import EntityCategory # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback # type: ignore
from homeassistant.helpers.update_coordinator import CoordinatorEntity # type: ignore
from homeassistant.helpers.device_registry import DeviceInfo # type: ignore

from .const import DOMAIN
from .coordinator import BookStackCoordinator

# Only allow a single sensor update at a time to avoid HA warnings about overlapping updates. This is important because the coordinator 
# updates all sensors when it fetches new data, and we don't want multiple sensors trying to update simultaneously if the coordinator fetches 
# data more frequently than the sensor update time.
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

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "connectivity"  # resolved via strings.json entity section

    def __init__(
        self,
        coordinator: BookStackCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the connectivity sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_connectivity"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def is_on(self) -> bool:
        """Return True when BookStack was successfully reached on the last poll.

        The coordinator sets is_available=True after a successful fetch and is_available=False on any connection error or auth failure.
        """
        return self.coordinator.is_available
