"""Number entities for AirTouch 3 zone control."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MIN_TEMP, MAX_TEMP
from .coordinator import AirTouch3Coordinator
from .models import ZoneState
from .switch import get_zone_device_info

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up number entities for zone control."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []

    for zone in coordinator.data.zones:
        entities.append(AirTouch3ZoneValueNumber(coordinator, zone.zone_number))

    async_add_entities(entities)


class AirTouch3ZoneValueNumber(CoordinatorEntity[AirTouch3Coordinator], NumberEntity):
    """Number entity for zone value control (temperature or damper percent).

    This entity dynamically changes its behavior based on the zone's control mode:
    - Temperature mode: Controls setpoint in °C (for zones with sensors)
    - Percentage mode: Controls damper opening percentage
    """

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    _attr_name = "Setpoint"  # Device name already includes zone name

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize zone value number entity."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    @property
    def _zone_state(self) -> ZoneState:
        """Get current zone state."""
        return self.coordinator.data.zones[self.zone_number]

    @property
    def native_value(self) -> float | None:
        """Return current value based on control mode."""
        zone = self._zone_state
        if zone.temperature_control and zone.has_sensor:
            # Temperature mode - return setpoint
            return float(zone.setpoint) if zone.setpoint is not None else None
        else:
            # Percentage mode - return damper percent
            return float(zone.damper_percent)

    @property
    def native_min_value(self) -> float:
        """Return minimum value based on control mode."""
        zone = self._zone_state
        if zone.temperature_control and zone.has_sensor:
            return float(MIN_TEMP)
        return 0.0

    @property
    def native_max_value(self) -> float:
        """Return maximum value based on control mode."""
        zone = self._zone_state
        if zone.temperature_control and zone.has_sensor:
            return float(MAX_TEMP)
        return 100.0

    @property
    def native_step(self) -> float:
        """Return step value based on control mode."""
        zone = self._zone_state
        if zone.temperature_control and zone.has_sensor:
            return 1.0  # 1°C steps
        return 5.0  # 5% steps for damper

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit based on control mode."""
        zone = self._zone_state
        if zone.temperature_control and zone.has_sensor:
            return UnitOfTemperature.CELSIUS
        return PERCENTAGE

    async def async_set_native_value(self, value: float) -> None:
        """Set the zone value (temperature or damper percent)."""
        zone = self._zone_state
        target = int(value)

        if zone.temperature_control and zone.has_sensor:
            # Temperature mode
            LOGGER.debug(
                "Setting zone %s temperature to %d°C", zone.name, target
            )
            await self.coordinator.client.zone_set_value(
                self.zone_number, target, is_temperature=True
            )
        else:
            # Percentage mode
            LOGGER.debug(
                "Setting zone %s damper to %d%%", zone.name, target
            )
            await self.coordinator.client.zone_set_value(
                self.zone_number, target, is_temperature=False
            )

        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        zone = self._zone_state
        return {
            "control_mode": "temperature" if zone.temperature_control else "percentage",
            "has_sensor": zone.has_sensor,
            "damper_percent": zone.damper_percent,
            "setpoint": zone.setpoint,
        }

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}_setpoint"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info - zone sub-device."""
        return get_zone_device_info(self.coordinator, self.zone_number)
