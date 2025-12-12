"""Button entities for AirTouch 3."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MIN_TEMP, MAX_TEMP
from .coordinator import AirTouch3Coordinator
from .sensor import AirTouch3ZoneSetpointSensor
from .switch import get_main_device_info, get_zone_device_info

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up button entities."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []

    entities.append(AirTouch3SyncTimeButton(coordinator))

    # Setpoint up/down buttons for all zones
    # Zones with sensors: adjusts temperature setpoint
    # Zones without sensors: adjusts damper percentage
    for zone in coordinator.data.zones:
        entities.append(AirTouch3SetpointUpButton(coordinator, zone.zone_number))
        entities.append(AirTouch3SetpointDownButton(coordinator, zone.zone_number))

    async_add_entities(entities)


class AirTouch3SetpointUpButton(CoordinatorEntity[AirTouch3Coordinator], ButtonEntity):
    """Button to increase zone setpoint.

    For zones with temperature sensors: increases temperature setpoint by 1°C
    For zones without sensors: increases damper percentage by 5%
    """

    _attr_has_entity_name = True
    _attr_name = "Setpoint Up"

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize setpoint up button."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    @property
    def _is_temperature_mode(self) -> bool:
        """Check if zone is in temperature mode."""
        zone = self.coordinator.data.zones[self.zone_number]
        return zone.has_sensor and zone.temperature_control

    @property
    def icon(self) -> str:
        """Return icon based on mode."""
        return "mdi:thermometer-chevron-up" if self._is_temperature_mode else "mdi:fan-chevron-up"

    async def async_press(self) -> None:
        """Handle button press - increase setpoint."""
        LOGGER.debug("Setpoint UP pressed for zone %d", self.zone_number)
        zone = self.coordinator.data.zones[self.zone_number]

        # Set optimistic value immediately
        if self._is_temperature_mode and zone.setpoint is not None:
            new_value = min(zone.setpoint + 1, MAX_TEMP)
        else:
            new_value = min(zone.damper_percent + 5, 100)

        AirTouch3ZoneSetpointSensor.set_optimistic_value(
            self.coordinator.data.device_id, self.zone_number, new_value
        )
        self.coordinator.async_set_updated_data(self.coordinator.data)

        await self.coordinator.client.zone_value_up(self.zone_number)
        await self.coordinator.async_request_refresh()

    @property
    def unique_id(self) -> str:
        """Unique ID for setpoint up button."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}_setpoint_up"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - zone sub-device."""
        return get_zone_device_info(self.coordinator, self.zone_number)


class AirTouch3SetpointDownButton(CoordinatorEntity[AirTouch3Coordinator], ButtonEntity):
    """Button to decrease zone setpoint.

    For zones with temperature sensors: decreases temperature setpoint by 1°C
    For zones without sensors: decreases damper percentage by 5%
    """

    _attr_has_entity_name = True
    _attr_name = "Setpoint Down"

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize setpoint down button."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    @property
    def _is_temperature_mode(self) -> bool:
        """Check if zone is in temperature mode."""
        zone = self.coordinator.data.zones[self.zone_number]
        return zone.has_sensor and zone.temperature_control

    @property
    def icon(self) -> str:
        """Return icon based on mode."""
        return "mdi:thermometer-chevron-down" if self._is_temperature_mode else "mdi:fan-chevron-down"

    async def async_press(self) -> None:
        """Handle button press - decrease setpoint."""
        LOGGER.debug("Setpoint DOWN pressed for zone %d", self.zone_number)
        zone = self.coordinator.data.zones[self.zone_number]

        # Set optimistic value immediately
        if self._is_temperature_mode and zone.setpoint is not None:
            new_value = max(zone.setpoint - 1, MIN_TEMP)
        else:
            new_value = max(zone.damper_percent - 5, 0)

        AirTouch3ZoneSetpointSensor.set_optimistic_value(
            self.coordinator.data.device_id, self.zone_number, new_value
        )
        self.coordinator.async_set_updated_data(self.coordinator.data)

        await self.coordinator.client.zone_value_down(self.zone_number)
        await self.coordinator.async_request_refresh()

    @property
    def unique_id(self) -> str:
        """Unique ID for setpoint down button."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}_setpoint_down"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - zone sub-device."""
        return get_zone_device_info(self.coordinator, self.zone_number)


class AirTouch3SyncTimeButton(CoordinatorEntity[AirTouch3Coordinator], ButtonEntity):
    """Button to push local time to the AirTouch 3 unit."""

    _attr_has_entity_name = True
    _attr_name = "Sync Time"
    _attr_icon = "mdi:clock-check-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AirTouch3Coordinator) -> None:
        """Initialize sync time button."""
        super().__init__(coordinator)

    async def async_press(self) -> None:
        """Handle button press - send time sync command."""
        now = dt_util.now()
        LOGGER.debug("Sync Time pressed, sending %s", now.isoformat())

        if await self.coordinator.client.sync_time(now):
            notification_id = f"{self.coordinator.data.device_id}_time_sync"
            self.hass.components.persistent_notification.async_create(
                "Time Updated",
                title="AirTouch 3",
                notification_id=notification_id,
            )
        else:
            LOGGER.error("Failed to sync time for AirTouch 3 device %s", self.coordinator.data.device_id)

    @property
    def unique_id(self) -> str:
        """Unique ID for sync time button."""
        return f"{self.coordinator.data.device_id}_sync_time"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - main device."""
        return get_main_device_info(self.coordinator)
