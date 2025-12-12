"""Button entities for AirTouch 3."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MIN_TEMP, MAX_TEMP
from .coordinator import AirTouch3Coordinator
from .sensor import AirTouch3ZoneSetpointSensor
from .switch import get_zone_device_info

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up button entities."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []

    # Setpoint up/down buttons for zones with temperature sensors
    for zone in coordinator.data.zones:
        if zone.has_sensor:
            entities.append(AirTouch3SetpointUpButton(coordinator, zone.zone_number))
            entities.append(AirTouch3SetpointDownButton(coordinator, zone.zone_number))

    async_add_entities(entities)


class AirTouch3SetpointUpButton(CoordinatorEntity[AirTouch3Coordinator], ButtonEntity):
    """Button to increase zone setpoint by 1 degree.

    Only available for zones that have a temperature sensor assigned.
    """

    _attr_has_entity_name = True
    _attr_name = "Setpoint Up"
    _attr_icon = "mdi:thermometer-chevron-up"

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize setpoint up button."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    async def async_press(self) -> None:
        """Handle button press - increase setpoint."""
        LOGGER.debug("Setpoint UP pressed for zone %d", self.zone_number)

        # Set optimistic value immediately
        zone = self.coordinator.data.zones[self.zone_number]
        if zone.setpoint is not None:
            new_setpoint = min(zone.setpoint + 1, MAX_TEMP)
            AirTouch3ZoneSetpointSensor.set_optimistic_value(
                self.coordinator.data.device_id, self.zone_number, new_setpoint
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
    """Button to decrease zone setpoint by 1 degree.

    Only available for zones that have a temperature sensor assigned.
    """

    _attr_has_entity_name = True
    _attr_name = "Setpoint Down"
    _attr_icon = "mdi:thermometer-chevron-down"

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize setpoint down button."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    async def async_press(self) -> None:
        """Handle button press - decrease setpoint."""
        LOGGER.debug("Setpoint DOWN pressed for zone %d", self.zone_number)

        # Set optimistic value immediately
        zone = self.coordinator.data.zones[self.zone_number]
        if zone.setpoint is not None:
            new_setpoint = max(zone.setpoint - 1, MIN_TEMP)
            AirTouch3ZoneSetpointSensor.set_optimistic_value(
                self.coordinator.data.device_id, self.zone_number, new_setpoint
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
