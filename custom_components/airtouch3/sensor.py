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

    # Zone damper percentage, temperature, and control mode
    for zone in coordinator.data.zones:
        entities.append(AirTouch3DamperSensor(coordinator, zone.zone_number))
        entities.append(AirTouch3ZoneTemperatureSensor(coordinator, zone.zone_number))
        # Control mode sensor only for zones with sensors
        if zone.has_sensor:
            entities.append(AirTouch3ZoneControlModeSensor(coordinator, zone.zone_number))

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

        # Check touchpad 1 (assigned_zone is 0-indexed, -1 means unassigned)
        tp1 = data.touchpads[0]
        if tp1.assigned_zone == self.zone_number and tp1.temperature is not None and tp1.temperature > 0:
            LOGGER.debug(
                "Zone %d: Using touchpad1, temp=%d",
                self.zone_number, tp1.temperature
            )
            return tp1.temperature, "touchpad1", False

        # Check touchpad 2
        tp2 = data.touchpads[1]
        if tp2.assigned_zone == self.zone_number and tp2.temperature is not None and tp2.temperature > 0:
            LOGGER.debug(
                "Zone %d: Using touchpad2, temp=%d",
                self.zone_number, tp2.temperature
            )
            return tp2.temperature, "touchpad2", False

        # Check wireless sensor 1 for this zone (slot = zone_number * 2)
        sensor1_index = self.zone_number * 2
        if sensor1_index < len(data.sensors):
            sensor1 = data.sensors[sensor1_index]
            LOGGER.debug(
                "Zone %d: Checking sensor slot %d, available=%s, temp=%d",
                self.zone_number, sensor1_index, sensor1.available, sensor1.temperature
            )
            if sensor1.available:
                return sensor1.temperature, f"wireless_{sensor1_index + 1}", sensor1.low_battery

        # Check wireless sensor 2 for this zone (slot = zone_number * 2 + 1)
        sensor2_index = self.zone_number * 2 + 1
        if sensor2_index < len(data.sensors):
            sensor2 = data.sensors[sensor2_index]
            LOGGER.debug(
                "Zone %d: Checking sensor slot %d, available=%s, temp=%d",
                self.zone_number, sensor2_index, sensor2.available, sensor2.temperature
            )
            if sensor2.available:
                return sensor2.temperature, f"wireless_{sensor2_index + 1}", sensor2.low_battery

        LOGGER.debug("Zone %d: No temperature source found", self.zone_number)
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


class AirTouch3ZoneControlModeSensor(CoordinatorEntity[AirTouch3Coordinator], SensorEntity):
    """Sensor showing the current zone control mode (Temperature or Fan).

    Only available for zones that have a temperature sensor assigned.
    Uses optimistic updates - when the toggle button is pressed, the state
    immediately shows the expected new value, reverting after timeout if
    the actual state doesn't change.
    """

    _attr_has_entity_name = True
    _attr_name = "Control Mode"
    _attr_icon = "mdi:thermostat"

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize control mode sensor."""
        super().__init__(coordinator)
        self.zone_number = zone_number

    @property
    def native_value(self) -> str:
        """Return the current control mode.

        Uses coordinator's get_zone_control_mode which handles optimistic state.
        """
        is_temp_mode = self.coordinator.get_zone_control_mode(self.zone_number)
        return "Temperature" if is_temp_mode else "Fan"

    @property
    def icon(self) -> str:
        """Return icon based on current mode."""
        is_temp_mode = self.coordinator.get_zone_control_mode(self.zone_number)
        return "mdi:thermometer" if is_temp_mode else "mdi:fan"

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}_control_mode"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - zone sub-device."""
        return get_zone_device_info(self.coordinator, self.zone_number)
