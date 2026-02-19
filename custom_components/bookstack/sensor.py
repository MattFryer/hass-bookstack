"""Sensor and Binary Sensor entities for BookStack integration

This module defines all of the Home Assistant Sensor and Binary Sensor entities exposed by the integration. Each entity reads data from 
the BookStackCoordinator, which is responsible for fetching data from the BookStack API and providing it to the entities.

All entities inherit from CoordinatorEntity, which wires them into the DataUpdateCoordinator's listener system. When the coordinator 
fetches fresh data, it notifies all subscribed entities, which then push their new state to HA.

async_setup_entry also registers a coordinator listener that dynamically creates new BookStackShelfSensor entities if shelves are added 
to BookStack between restarts, without requiring a full reload of HA .
"""
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

# Limit entity updates to one at a time to avoid overwhelming the BookStack API if many shelves are added at once.
PARALLEL_UPDATES = 1

# Map coordinator data keys to sensor names and icons for the static aggregate sensors. These sensors show overall counts of shelves, 
# books, chapters, pages, users, images, and attachments across the entire BookStack instance. The keys correspond to the data returned 
# by the coordinator's API calls, and the names/icons are used for the sensor entities in HA.
STATIC_SENSORS: dict[str, tuple[str, str]] = {
    "shelves": ("Shelves", "mdi:bookshelf"),
    "books": ("Books", "mdi:book-multiple"),
    "chapters": ("Chapters", "mdi:book-open"),
    "pages": ("Pages", "mdi:file-document-multiple"),
    "users": ("Users", "mdi:account-multiple"),
    "images": ("Images", "mdi:image-multiple"),
    "attachments": ("Attachments", "mdi:paperclip"),
}

# For per-shelf sensors, we define a list that specify the data key for the shelf metric (e.g., "book_count"), a name suffix to append 
# to the shelf name for the sensor's display name in HA (e.g., "Books"), an ID suffix for the HA unique_id (e.g., "books"), and an icon.
# This allows us to easily create multiple sensors for each shelf based on the same pattern.
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
    """Set up the BookStack sensors for a config entry
    
    Call by HA when the "sensor" platform is being set up for this integration. We create sensor entities based on the data from the 
    coordinator, and we also register a listener on the coordinator to dynamically add new shelf sensors if shelves are added to 
    BookStack after startup.
    """
    # Get the coordinator instance from the config entry's runtime_data, which was set up in __init__.py. The coordinator contains the 
    # latest data fetched from the BookStack API. We will pass this coordinator to the sensor entities so they can read the data and 
    # subscribe to updates.
    coordinator: BookStackCoordinator = entry.runtime_data

    # Start with the static aggregate sensors that show overall counts. We create one BookStackSensor for each key in  STATIC_SENSORS, 
    # passing the coordinator, config entry, data key, name, and icon to the sensor constructor.
    entities: list[SensorEntity | BinarySensorEntity] = [
        BookStackSensor(coordinator, entry, key, name, icon)
        for key, (name, icon) in STATIC_SENSORS.items()
    ]

    # If per-shelf sensors are enabled in the options, we create sensors for each shelf. We loop through the shelves data from the 
    # coordinator, and for each shelf, we create a BookStackShelfSensor for each metric defined in SHELF_SENSOR_TYPES above, passing 
    # the coordinator, config entry, shelf data, data key, name suffix, ID suffix, and icon to the sensor constructor so that it can 
    # create sensors for each shelf with the appropriate names and unique IDs.
    if coordinator.per_shelf_enabled:
        for shelf in coordinator.shelves_data:
            for data_key, name_suffix, id_suffix, icon in SHELF_SENSOR_TYPES:
                entities.append(
                    BookStackShelfSensor(coordinator, entry, shelf, data_key, name_suffix, id_suffix, icon)
                )

    # Add the latest updated page sensor
    entities.append(BookStackLastUpdatedPageSensor(coordinator, entry))

    # Add the availability binary sensor, which indicates whether the coordinator was able to successfully fetch data from the BookStack 
    # API on the last update. 
    entities.append(BookStackAvailabilitySensor(coordinator, entry))

    # Call HA to add the entities we created. This will register them with HA and make them available in the UI. The coordinator will 
    # call their update methods when new data is available.
    async_add_entities(entities)

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
            # Update the known_shelf_ids set to include the new IDs, so we don't create duplicate sensors on the next update.
            known_shelf_ids = current_ids

    # Register the listener on the coordinator so that _handle_coordinator_update is called whenever the coordinator fetches new data. 
    # This allows us to dynamically add sensors for new shelves.
    coordinator.async_add_listener(_handle_coordinator_update)


def _device_info(coordinator: BookStackCoordinator, entry: ConfigEntry) -> DeviceInfo:
    """Return shared DeviceInfo for all BookStack entities.
    
    All entities in this integration belong to the same device, which represents the BookStack instance. This function constructs a 
    DeviceInfo object in the HA device registry with identifiers, name, manufacturer, model, software version, and configuration URL 
    (link to the BookStack instance). 
    """
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.system_data.get("instance_id", entry.entry_id))}, # Use the BookStack instance ID from the API if available, otherwise fall back to the config entry ID to ensure uniqueness.
        name=f"BookStack ({entry.data['url']})", # Use the BookStack instance URL in the device name to make it easily identifiable in HA, especially if users have multiple BookStack instances.
        manufacturer="BookStack",
        model="BookStack",
        sw_version=coordinator.version, # Uses the BookStack version fetched from the API as the device's software version in HA, which can be helpful for debugging and support.
        configuration_url=entry.data["url"], # Adds a "Visit" link on the device page in HA, linking to the BookStack instance URL
    )


class BookStackSensor(CoordinatorEntity[BookStackCoordinator], SensorEntity):
    """Generic BookStack numeric sensor for the aggregate counts
    
    Represents a single numeric metric from the coordinator's data, such as total shelves, books, chapters, pages, users, images, or 
    attachments.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT # The HA sensor state class indicates that this sensor represents a measurement that can be used for statistics and long-term recording. This allows users to see historical data and use it in automations based on trends.
    _attr_has_entity_name = True # tells HA to prefix the entity's display name with the device name e.g. "BookStack (https://...) Books". This is the recommended modern HA pattern.

    def __init__(
        self,
        coordinator: BookStackCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        """Initialize the sensor with the coordinator, config entry, data key, name, and icon."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}" # Ensure unique_id is unique across all sensors by combining the config entry ID with the specific data key for this sensor.
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def native_value(self) -> int | None:
        """Return the current value of the sensor.
        
        Returns None (which HA renders as "unavailable") if the coordinator has no data yet, which can happen on the first update 
        before the API response is received.
        """
        return self.coordinator.data.get(self._key) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        """Return False when the BookStack API was unreachable on the last update

        Overrides CoordinatorEntity.available to also check our custom is_available flag. Marking entities unavailable on failure is
        better than showing a stale value, which could mislead automations.
        """
        return self.coordinator.is_available and super().available


class BookStackShelfSensor(CoordinatorEntity[BookStackCoordinator], SensorEntity):
    """A numeric sensor for a single metric (books, chapters, or pages) on a specific shelf.
    
    These instances are created dynamically based on the shelves returned by the coordinator. Each sensor is tied to a specific shelf 
    ID and data key (e.g., "book_count"), and reads its value from the coordinator's shelves_data for that shelf. 
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
        """ Initialise the per-shelf sensor"""
        super().__init__(coordinator)
        # Store the shelf ID so we can look up the current data for this shelf in the coordinator's shelves_data rather than holding a 
        # stale reference to the original shelf dict.
        self._shelf_id: int = shelf["id"]
        self._data_key = data_key
        self._attr_name = f"{shelf['name']} {name_suffix}"
        self._attr_icon = icon
        # Include the shelf ID in the unique_id to ensure uniqueness across multiple shelves if they have the same name. The unique_id also
        # remains stable if the shelf is renamed.
        self._attr_unique_id = f"{entry.entry_id}_shelf_{shelf['id']}_{id_suffix}"
        self._attr_device_info = _device_info(coordinator, entry)

    def _current_shelf(self) -> dict[str, Any]:
        """Find the shelf's current data in the coordinator.shelves_data based on the shelf ID"""
        for shelf in self.coordinator.shelves_data:
            if shelf["id"] == self._shelf_id:
                return shelf
        return {}

    @property
    def native_value(self) -> int:
        """Return the current value of the sensor for this shelf and data key."""
        return self._current_shelf().get(self._data_key, 0)

    @property
    def available(self) -> bool:
        """Return False when the BookStack API was unreachable on the last update."""
        return self.coordinator.is_available and super().available


class BookStackLastUpdatedPageSensor(CoordinatorEntity[BookStackCoordinator], SensorEntity):
    """Sensor reporting the timestamp of the last page update in BookStack.

    Useful for tracking recent activity in BookStack and triggering automations based on recent edits. The sensor contains multiple
    attributes information and attributes as follows:
        State:    ISO 8601 datetime o(HA-localised) of the most recently updated page.
        Attributes (accessible in HA as sensor attributes and in automations using trigger.to_state.attributes):
            page_name       — display name of the updated page
            page_id         — BookStack internal page ID
            updated_by      — display name of the user who made the edit
            updated_by_id   — BookStack internal user ID
            page_url        — direct link to the page in BookStack
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_has_entity_name = True
    _attr_icon = "mdi:file-clock"

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
        """Return False when BookStack was unreachable on the last poll."""
        return self.coordinator.is_available and super().available

    @property
    def native_value(self) -> datetime | None:
        """Return the current value of the sensor, converting the BookStack API's updated_at ISO timestamp to a HA-localised datetime"""
        updated_at = self.coordinator.last_updated_page.get("updated_at")
        if not updated_at:
            return None
        try:
            # Python's fromisoformat doesn't accept the "Z" UTC suffix before Python 3.11, so we normalise it to "+00:00" first to support older Python versions.
            utc_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            # Convert the UTC datetime to the users configured timezone using HA's dt_util.as_local, which is the recommended way to handle timezones in HA.
            return dt_util.as_local(utc_dt)
        except (ValueError, AttributeError):
            # If the timestamp returned by the API is in an unexpected format, we return None rather than crashing the sensor.
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes about the last updated page, such as page name, page ID, who updated it, and a link to the page."""
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

    Shown under the Diagnostic section of the device page. State: on = reachable, off = unreachable.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY # Gives the sensor the correct device class in HA which affects the icon and how the values are displayed ("connector" or "disconnected")
    _attr_entity_category = EntityCategory.DIAGNOSTIC # Causes the sensor to be shown in the "Diagnostics" section of the device page in HA
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
        
        The coordinator sets is_available=True after a successful fetch and is_available=False on any connection error or auth failure."""
        return self.coordinator.is_available