from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import BookStackCoordinator

# Silver: parallel-updates — BookStack is a single HTTP service; serialise
# entity updates to avoid hammering it with concurrent requests.
PARALLEL_UPDATES = 1

STATIC_SENSORS: dict[str, tuple[str, str]] = {
    "shelves": ("Shelves", "mdi:bookshelf"),
    "books": ("Books", "mdi:book-multiple"),
    "chapters": ("Chapters", "mdi:book-open"),
    "pages": ("Pages", "mdi:file-document-multiple"),
    "users": ("Users", "mdi:account-multiple"),
    "images": ("Images", "mdi:image-multiple"),
    "attachments": ("Attachments", "mdi:paperclip-multiple"),
}

SHELF_SENSOR_TYPES: list[tuple[str, str, str, str]] = [
    ("book_count",    "Books",    "books",    "mdi:book-multiple"),
    ("chapter_count", "Chapters", "chapters", "mdi:book-open"),
    ("page_count",    "Pages",    "pages",    "mdi:file-document-multiple"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    # Bronze: runtime-data — read coordinator from entry.runtime_data.
    coordinator: BookStackCoordinator = entry.runtime_data

    entities: list[SensorEntity | BinarySensorEntity] = [
        BookStackSensor(coordinator, entry, key, name, icon)
        for key, (name, icon) in STATIC_SENSORS.items()
    ]

    if coordinator.per_shelf_enabled:
        for shelf in coordinator.shelves_data:
            for data_key, name_suffix, id_suffix, icon in SHELF_SENSOR_TYPES:
                entities.append(
                    BookStackShelfSensor(coordinator, entry, shelf, data_key, name_suffix, id_suffix, icon)
                )

    entities.append(BookStackLastUpdatedPageSensor(coordinator, entry))
    entities.append(BookStackAvailabilitySensor(coordinator, entry))

    async_add_entities(entities)

    known_shelf_ids: set[int] = {s["id"] for s in coordinator.shelves_data}

    @callback
    def _handle_coordinator_update() -> None:
        nonlocal known_shelf_ids
        current_ids = {s["id"] for s in coordinator.shelves_data}
        new_ids = current_ids - known_shelf_ids
        if new_ids:
            new_entities: list[SensorEntity] = []
            for shelf in coordinator.shelves_data:
                if shelf["id"] in new_ids:
                    for data_key, name_suffix, id_suffix, icon in SHELF_SENSOR_TYPES:
                        new_entities.append(
                            BookStackShelfSensor(
                                coordinator, entry, shelf, data_key, name_suffix, id_suffix, icon
                            )
                        )
            async_add_entities(new_entities)
            known_shelf_ids = current_ids

    coordinator.async_add_listener(_handle_coordinator_update)


def _device_info(coordinator: BookStackCoordinator, entry: ConfigEntry) -> DeviceInfo:
    """Return shared DeviceInfo for all BookStack entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.system_data.get("instance_id", entry.entry_id))},
        name=f"BookStack ({entry.data['url']})",
        manufacturer="BookStack",
        model="BookStack",
        sw_version=coordinator.version,
        configuration_url=entry.data["url"],
    )


class BookStackSensor(CoordinatorEntity[BookStackCoordinator], SensorEntity):
    """Generic BookStack sensor for aggregate counts."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    # Bronze: has-entity-name — HA will prefix with the device name automatically.
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BookStackCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get(self._key) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        """Silver: entity-unavailable — mark unavailable when coordinator fails."""
        return self.coordinator.is_available and super().available


class BookStackShelfSensor(CoordinatorEntity[BookStackCoordinator], SensorEntity):
    """Sensor for a single metric (books, chapters, or pages) on a specific shelf."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BookStackCoordinator,
        entry: ConfigEntry,
        shelf: dict[str, Any],
        data_key: str,
        name_suffix: str,
        id_suffix: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._shelf_id: int = shelf["id"]
        self._data_key = data_key
        self._attr_name = f"{shelf['name']} {name_suffix}"
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_shelf_{shelf['id']}_{id_suffix}"
        self._attr_device_info = _device_info(coordinator, entry)

    def _current_shelf(self) -> dict[str, Any]:
        for shelf in self.coordinator.shelves_data:
            if shelf["id"] == self._shelf_id:
                return shelf
        return {}

    @property
    def native_value(self) -> int:
        return self._current_shelf().get(self._data_key, 0)

    @property
    def available(self) -> bool:
        """Silver: entity-unavailable — mark unavailable when coordinator fails."""
        return self.coordinator.is_available and super().available


class BookStackLastUpdatedPageSensor(CoordinatorEntity[BookStackCoordinator], SensorEntity):
    """Sensor reporting the date/time of the last page update in BookStack.

    State:    ISO 8601 datetime of the most recently updated page.
    Attributes:
        page_name       — display name of the updated page
        page_id         — BookStack internal page ID
        updated_by      — display name of the user who made the edit
        updated_by_id   — BookStack internal user ID
        page_url        — direct link to the page in BookStack
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_icon = "mdi:file-document-clock"

    def __init__(
        self,
        coordinator: BookStackCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._attr_name = "Last Updated Page"
        self._attr_unique_id = f"{entry.entry_id}_last_updated_page"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def available(self) -> bool:
        """Silver: entity-unavailable — mark unavailable when coordinator fails."""
        return self.coordinator.is_available and super().available

    @property
    def native_value(self) -> datetime | None:
        updated_at = self.coordinator.last_updated_page.get("updated_at")
        if not updated_at:
            return None
        try:
            utc_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            return dt_util.as_local(utc_dt)
        except (ValueError, AttributeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        page = self.coordinator.last_updated_page
        return {
            "page_name": page.get("name"),
            "page_id": page.get("id"),
            "updated_by": page.get("updated_by_name"),
            "updated_by_id": page.get("updated_by_id"),
            "page_url": page.get("url"),
        }


class BookStackAvailabilitySensor(CoordinatorEntity[BookStackCoordinator], BinarySensorEntity):
    """Binary sensor indicating whether BookStack is reachable.

    Shown under the Diagnostic section of the device page.
    State: on = reachable, off = unreachable.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

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
        """Return True when BookStack was successfully reached on the last poll."""
        return self.coordinator.is_available