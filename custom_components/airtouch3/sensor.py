"""Sensor entities for AirTouch 3."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AirTouch3Coordinator
from .switch import get_zone_device_info, get_main_device_info

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors from config entry."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    # AC unit temperatures
    for ac in coordinator.data.ac_units:
        entities.append(AirTouch3AcTemperatureSensor(coordinator, ac.ac_number))

    # Zone damper percentage, temperature, and setpoint
    for zone in coordinator.data.zones:
        entities.append(AirTouch3DamperSensor(coordinator, zone.zone_number))
        entities.append(AirTouch3ZoneTemperatureSensor(coordinator, zone.zone_number))
        # Setpoint sensor for all zones (temperature setpoint or damper %)
        entities.append(AirTouch3ZoneSetpointSensor(coordinator, zone.zone_number))

    async_add_entities(entities)


class AirTouch3AcTemperatureSensor(CoordinatorEntity[AirTouch3Coordinator], SensorEntity):
    """Temperature sensor for an AC unit."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True

    def __init__(self, coordinator: AirTouch3Coordinator, ac_number: int) -> None:
        """Initialize AC temperature sensor."""
        super().__init__(coordinator)
        self.ac_number = ac_number
        name = coordinator.data.ac_units[ac_number].name
        self._attr_name = f"{name} Temperature"

    @property
    def native_value(self) -> float | None:
        """Return temperature value."""
        return float(self.coordinator.data.ac_units[self.ac_number].room_temp)

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self.coordinator.data.device_id}_ac_{self.ac_number}_temperature"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - main device."""
        return get_main_device_info(self.coordinator)


class AirTouch3ZoneTemperatureSensor(CoordinatorEntity[AirTouch3Coordinator], SensorEntity):
    """Temperature sensor for a zone.

    Follows the app logic: touchpad takes priority, then wireless sensor 1,
    then wireless sensor 2 for the zone.
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = "Temperature"  # Device name already includes zone name

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize zone temperature sensor."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    def _get_temperature_and_source(self) -> tuple[int | None, str | None, bool]:
        """Get temperature value, source name, and low battery flag.

        Returns (temperature, source, low_battery).
        Follows app logic: touchpad priority, then sensor1, then sensor2.
        """
        data = self.coordinator.data
        zone = data.zones[self.zone_number]

        # Check touchpad 1 (assigned_zone is 0-indexed, -1 means unassigned)
        tp1 = data.touchpads[0]
        if tp1.assigned_zone == self.zone_number and tp1.temperature is not None and tp1.temperature > 0:
            return tp1.temperature, "touchpad1", False

        # Check touchpad 2
        tp2 = data.touchpads[1]
        if tp2.assigned_zone == self.zone_number and tp2.temperature is not None and tp2.temperature > 0:
            return tp2.temperature, "touchpad2", False

        # For wireless sensors, use zone.has_sensor (sticky detection) to determine
        # if we should return the temperature. The sensor's "available" bit flickers
        # based on transmission timing, but the temperature value is still valid.
        if not zone.has_sensor:
            return None, None, False

        # Check wireless sensor 1 for this zone (slot = zone_number * 2)
        sensor1_index = self.zone_number * 2
        if sensor1_index < len(data.sensors):
            sensor1 = data.sensors[sensor1_index]
            # Return temperature if sensor has ever been detected (via has_sensor)
            # and has a valid temperature reading (> 0)
            if sensor1.temperature > 0:
                return sensor1.temperature, f"wireless_{sensor1_index + 1}", sensor1.low_battery

        # Check wireless sensor 2 for this zone (slot = zone_number * 2 + 1)
        sensor2_index = self.zone_number * 2 + 1
        if sensor2_index < len(data.sensors):
            sensor2 = data.sensors[sensor2_index]
            if sensor2.temperature > 0:
                return sensor2.temperature, f"wireless_{sensor2_index + 1}", sensor2.low_battery

        return None, None, False

    @property
    def native_value(self) -> float | None:
        """Return temperature value."""
        temp, _, _ = self._get_temperature_and_source()
        return float(temp) if temp is not None else None

    @property
    def available(self) -> bool:
        """Return True if any temperature source is available."""
        temp, _, _ = self._get_temperature_and_source()
        return temp is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes including source and battery status."""
        temp, source, low_battery = self._get_temperature_and_source()
        attrs: dict[str, Any] = {}
        if source:
            attrs["source"] = source
        if low_battery:
            attrs["low_battery"] = True
        return attrs

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}_temperature"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - zone sub-device."""
        return get_zone_device_info(self.coordinator, self.zone_number)


class AirTouch3DamperSensor(CoordinatorEntity[AirTouch3Coordinator], SensorEntity):
    """Damper percentage sensor for a zone."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_has_entity_name = True
    _attr_name = "Damper"  # Device name already includes zone name

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize damper sensor."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    @property
    def native_value(self) -> float | None:
        """Return damper opening percentage."""
        return float(self.coordinator.data.zones[self.zone_number].damper_percent)

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}_damper"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - zone sub-device."""
        return get_zone_device_info(self.coordinator, self.zone_number)


class AirTouch3ZoneSetpointSensor(CoordinatorEntity[AirTouch3Coordinator], SensorEntity):
    """Setpoint sensor for a zone.

    For zones with temperature sensors: shows target temperature (°C)
    For zones without sensors: shows target damper percentage (%)
    Supports optimistic updates when setpoint buttons are pressed.
    """

    _attr_state_class = None  # Disable LTS - unit changes between °C and % based on mode
    _attr_has_entity_name = True
    _attr_name = "Setpoint"

    # Class-level registry for optimistic setpoint values
    # Maps (device_id, zone_number) -> optimistic_value
    _optimistic_values: dict[tuple[str, int], int] = {}

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize setpoint sensor."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    @classmethod
    def set_optimistic_value(cls, device_id: str, zone_number: int, value: int) -> None:
        """Set an optimistic setpoint value (called by buttons)."""
        cls._optimistic_values[(device_id, zone_number)] = value

    @classmethod
    def clear_optimistic_value(cls, device_id: str, zone_number: int) -> None:
        """Clear the optimistic value (called after coordinator update)."""
        cls._optimistic_values.pop((device_id, zone_number), None)

    @property
    def _optimistic_key(self) -> tuple[str, int]:
        """Get the key for optimistic value lookup."""
        return (self.coordinator.data.device_id, self.zone_number)

    @property
    def _is_temperature_mode(self) -> bool:
        """Check if zone is in temperature mode (has sensor and temp control enabled)."""
        zone = self.coordinator.data.zones[self.zone_number]
        return zone.has_sensor and zone.temperature_control

    @property
    def native_value(self) -> float | None:
        """Return current setpoint value, preferring optimistic value."""
        zone = self.coordinator.data.zones[self.zone_number]

        # Check for optimistic value first
        optimistic = self._optimistic_values.get(self._optimistic_key)
        if optimistic is not None:
            return float(optimistic)

        # For zones with sensors in temp mode, return setpoint
        if self._is_temperature_mode and zone.setpoint is not None:
            return float(zone.setpoint)

        # For zones without sensors or in fan mode, return damper percent
        # When zone is OFF in fan mode, display 0% to match physical unit behavior
        # (the actual damper value is preserved and used when zone turns back on)
        if not zone.is_on:
            return 0.0
        return float(zone.damper_percent)

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update - clear optimistic value if actual matches."""
        zone = self.coordinator.data.zones[self.zone_number]
        optimistic = self._optimistic_values.get(self._optimistic_key)
        if optimistic is not None:
            # Check if actual value matches optimistic
            if self._is_temperature_mode:
                actual = zone.setpoint
            else:
                actual = zone.damper_percent
            if actual == optimistic:
                self.clear_optimistic_value(*self._optimistic_key)
        super()._handle_coordinator_update()

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class based on mode."""
        if self._is_temperature_mode:
            return SensorDeviceClass.TEMPERATURE
        return None  # No device class for percentage

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit based on mode."""
        if self._is_temperature_mode:
            return UnitOfTemperature.CELSIUS
        return PERCENTAGE

    @property
    def icon(self) -> str:
        """Return icon based on control mode."""
        if self._is_temperature_mode:
            return "mdi:thermometer"
        return "mdi:fan"

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}_setpoint"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - zone sub-device."""
        return get_zone_device_info(self.coordinator, self.zone_number)


