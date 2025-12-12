"""Button entities for AirTouch 3."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AirTouch3Coordinator
from .switch import get_zone_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up button entities."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []

    # Zone mode toggle buttons (only for zones with sensors)
    for zone in coordinator.data.zones:
        if zone.has_sensor:
            entities.append(AirTouch3ZoneModeToggleButton(coordinator, zone.zone_number))

    async_add_entities(entities)


class AirTouch3ZoneModeToggleButton(CoordinatorEntity[AirTouch3Coordinator], ButtonEntity):
    """Button to toggle zone between temperature and percentage control modes.

    Only available for zones that have a temperature sensor assigned.
    Pressing toggles between Temperature mode and Fan (percentage) mode.
    """

    _attr_has_entity_name = True
    _attr_name = "Toggle Control Mode"
    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize zone mode toggle button."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    async def async_press(self) -> None:
        """Handle button press - send toggle command."""
        await self.coordinator.client.zone_toggle_mode(self.zone_number)
        # Trigger optimistic update on the control mode sensor
        self.coordinator.set_optimistic_control_mode(
            self.zone_number,
            not self.coordinator.data.zones[self.zone_number].temperature_control
        )
        await self.coordinator.async_request_refresh()

    @property
    def unique_id(self) -> str:
        """Unique ID for mode toggle button."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}_mode_toggle"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - zone sub-device."""
        return get_zone_device_info(self.coordinator, self.zone_number)
