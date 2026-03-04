"""Sensor entities for the BookStack integration.

Defines all Home Assistant Sensor entities. Each reads from the
BookStackCoordinator which polls the BookStack API.

All entities inherit from CoordinatorEntity so they are automatically
notified whenever the coordinator fetches fresh data.

async_setup_entry also:
  - Removes stale shelf-sensor entities when shelves are deleted from
    BookStack (satisfying the Gold 'stale-devices' rule).
  - Registers a coordinator listener that dynamically creates sensors for
    shelves added after the initial setup (satisfying 'dynamic-devices').
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass, SensorDeviceClass # type: ignore
from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.core import HomeAssistant, callback # type: ignore
from homeassistant.helpers import entity_registry # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback # type: ignore
from homeassistant.helpers.update_coordinator import CoordinatorEntity # type: ignore
from homeassistant.helpers.device_registry import DeviceInfo # type: ignore
from homeassistant.util import dt as dt_util # type: ignore

from .const import DOMAIN
from .coordinator import BookStackCoordinator

# Only allow a single sensor update at a time to avoid HA warnings about overlapping updates. This is important because the coordinator 
# updates all sensors when it fetches new data, and we don't want multiple sensors trying to update simultaneously if the coordinator fetches 
# data more frequently than the sensor update time.
PARALLEL_UPDATES = 1

# Maps coordinator data-key -> (translation_key, icon).
# translation_key links to the "entity.sensor.<key>.name" entry in strings.json.
# Icons are also declared in translations/icons.json so HA can use them in the
# frontend without hardcoding them in Python (satisfies 'icon-translations').
STATIC_SENSORS: dict[str, tuple[str, str]] = {
    "shelves":     ("shelves",     "mdi:bookshelf"),
    "books":       ("books",       "mdi:book-multiple"),
    "chapters":    ("chapters",    "mdi:book-open"),
    "pages":       ("pages",       "mdi:file-document-multiple"),
    "users":       ("users",       "mdi:account-multiple"),
    "images":      ("images",      "mdi:image-multiple"),
    "attachments": ("attachments", "mdi:paperclip"),
}

# (data_key, translation_key_suffix, unique_id_suffix, icon)
SHELF_SENSOR_TYPES: list[tuple[str, str, str, str]] = [
    ("book_count",    "books",    "books",    "mdi:book-multiple"),
    ("chapter_count", "chapters", "chapters", "mdi:book-open"),
    ("page_count",    "pages",    "pages",    "mdi:file-document-multiple"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BookStack sensor entities for a config entry."""
    coordinator: BookStackCoordinator = entry.runtime_data

    # --- Static aggregate count sensors ---
    entities: list[SensorEntity] = [
        BookStackSensor(coordinator, entry, key, translation_key, icon)
        for key, (translation_key, icon) in STATIC_SENSORS.items()
    ]

    # --- Per-shelf sensors (optional) ---
    if coordinator.per_shelf_enabled:
        for shelf in coordinator.shelves_data:
            for data_key, tk_suffix, id_suffix, icon in SHELF_SENSOR_TYPES:
                entities.append(
                    BookStackShelfSensor(
                        coordinator, entry, shelf, data_key, tk_suffix, id_suffix, icon
                    )
                )

    # --- Last-updated-page sensor ---
    entities.append(BookStackLastUpdatedPageSensor(coordinator, entry))

    # Call HA to add the entities we created. This will register them with HA and make them available in the UI. The coordinator will 
    # call their update methods when new data is available.
    async_add_entities(entities)

    # Remove entity registry entries for shelves that no longer exist in
    # BookStack, keeping the registry clean after shelf deletions.
    if coordinator.per_shelf_enabled:
        registry = entity_registry.async_get(hass)
        live_shelf_ids = {s["id"] for s in coordinator.shelves_data}
        for entity_entry in entity_registry.async_entries_for_config_entry(registry, entry.entry_id):
            uid = entity_entry.unique_id
            # Shelf UIDs follow the pattern: "<entry_id>_shelf_<shelf_id>_<suffix>"
            if "_shelf_" in uid:
                try:
                    shelf_id = int(uid.split("_shelf_")[1].split("_")[0])
                    if shelf_id not in live_shelf_ids:
                        registry.async_remove(entity_entry.entity_id)
                except (ValueError, IndexError):
                    pass

    # Track which shelf IDs we have already created sensors for, so that when the coordinator updates with new shelves, we can check if 
    # there are new shelves to create sensors for. We use a set of shelf IDs for easy lookup.
    known_shelf_ids: set[int] = {s["id"] for s in coordinator.shelves_data}

    @callback
    def _handle_coordinator_update() -> None:
        """Check for new shelves and add sensors for them if needed when the coordinator updates with new data.
        
        The @callback decorator tells HA that this function is a callback that should be run in the event loop (i.e. synchronously). This 
        is important because the coordinator calls its listeners synchronously after fetching new data, so this function needs to be able 
        to run synchronously without blocking the event loop.

        We compare the current shelf IDs from the coordinator's shelves_data with the known_shelf_ids set. If there are any new IDs, we 
        create new sensors for them and add them to HA. After adding new sensors, we update the known_shelf_ids set to include the new IDs.
        """
        nonlocal known_shelf_ids
        current_ids = {s["id"] for s in coordinator.shelves_data}
        new_ids = current_ids - known_shelf_ids
        if new_ids and coordinator.per_shelf_enabled:
            new_entities: list[SensorEntity] = [
                BookStackShelfSensor(
                    coordinator, entry, shelf, data_key, tk_suffix, id_suffix, icon
                )
                for shelf in coordinator.shelves_data
                if shelf["id"] in new_ids
                for data_key, tk_suffix, id_suffix, icon in SHELF_SENSOR_TYPES
            ]
            async_add_entities(new_entities)
            # Update the known_shelf_ids set to include the new IDs, so we don't create duplicate sensors on the next update.
            known_shelf_ids = current_ids

    # Register the listener on the coordinator so that _handle_coordinator_update is called whenever the coordinator fetches new data. 
    # This allows us to dynamically add sensors for new shelves.
    coordinator.async_add_listener(_handle_coordinator_update)


def _device_info(coordinator: BookStackCoordinator, entry: ConfigEntry) -> DeviceInfo:
    """Return shared DeviceInfo for all BookStack entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"BookStack ({entry.data['url']})",
        manufacturer="BookStack",
        model="BookStack",
        sw_version=coordinator.version,
        configuration_url=entry.data["url"],
    )


class BookStackSensor(CoordinatorEntity[BookStackCoordinator], SensorEntity):
    """Numeric sensor for one of the BookStack-wide aggregate counts.

    Covers shelves, books, chapters, pages, users, images, and attachments.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BookStackCoordinator,
        entry: ConfigEntry,
        key: str,
        translation_key: str,
        icon: str,
    ) -> None:
        """Initialise the aggregate count sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = translation_key  # resolved via strings.json entity section
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def native_value(self) -> int | None:
        """Return the current count, cast to int to guard against float API responses."""
        val = self.coordinator.data.get(self._key) if self.coordinator.data else None
        return int(val) if val is not None else None

    @property
    def available(self) -> bool:
        """Return False when BookStack was unreachable on the last poll."""
        return self.coordinator.is_available and super().available


class BookStackShelfSensor(CoordinatorEntity[BookStackCoordinator], SensorEntity):
    """Numeric sensor for one metric (books, chapters, or pages) on a specific shelf.

    Created dynamically per shelf; the shelf name is user-defined content from
    BookStack so the entity name is built at runtime rather than via a
    translation key.
    """

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
        """Initialise the per-shelf sensor."""
        super().__init__(coordinator)
        self._shelf_id: int = shelf["id"]
        self._data_key = data_key
        # Dynamic name: shelf name + metric suffix (e.g. "Home Network Books").
        # No translation_key here because the shelf name is user content.
        self._attr_name = f"{shelf['name']} {name_suffix.capitalize()}"
        self._attr_icon = icon
        # Shelf ID in the unique_id keeps it stable even after a shelf rename.
        self._attr_unique_id = f"{entry.entry_id}_shelf_{shelf['id']}_{id_suffix}"
        self._attr_device_info = _device_info(coordinator, entry)

    def _current_shelf(self) -> dict[str, Any]:
        """Locate this shelf's current data in coordinator.shelves_data."""
        for shelf in self.coordinator.shelves_data:
            if shelf["id"] == self._shelf_id:
                return shelf
        return {}

    @property
    def native_value(self) -> int:
        """Return the shelf metric value, cast to int."""
        return int(self._current_shelf().get(self._data_key, 0))

    @property
    def available(self) -> bool:
        """Return False when BookStack was unreachable on the last poll."""
        return self.coordinator.is_available and super().available
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the BookStack shelf ID as an entity attribute."""
        return {"shelf_id": self._shelf_id}


class BookStackLastUpdatedPageSensor(CoordinatorEntity[BookStackCoordinator], SensorEntity):
    """Sensor reporting the timestamp of the most recently updated BookStack page.

    State: HA-localised ISO 8601 datetime of the last page edit.
    Attributes:
        page_name     – display name of the updated page
        page_id       – BookStack internal page ID
        updated_by    – display name of the editing user
        updated_by_id – BookStack internal user ID
        page_url      – direct link to the page in BookStack
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_translation_key = "last_updated_page"

    def __init__(
        self,
        coordinator: BookStackCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the last-updated-page sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_last_updated_page"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def available(self) -> bool:
        """Return False when BookStack was unreachable on the last poll."""
        return self.coordinator.is_available and super().available

    @property
    def native_value(self) -> datetime | None:
        """Return the most-recently-updated page timestamp in the HA local timezone."""
        updated_at = self.coordinator.last_updated_page.get("updated_at")
        if not updated_at:
            return None
        try:
            # fromisoformat does not accept 'Z' before Python 3.11; normalise first.
            utc_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            return dt_util.as_local(utc_dt)
        except (ValueError, AttributeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return supplemental page metadata as entity attributes."""
        page = self.coordinator.last_updated_page
        return {
            "page_name":     page.get("name"),
            "page_id":       page.get("id"),
            "updated_by":    page.get("updated_by_name"),
            "updated_by_id": page.get("updated_by_id"),
            "page_url":      page.get("url"),
        }