"""Sensor entities for AirTouch 3."""

from __future__ import annotations

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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensors from config entry."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    # AC room temperatures
    for ac in coordinator.data.ac_units:
        entities.append(AirTouch3TemperatureSensor(coordinator, "ac", ac.ac_number))

    # Zone damper percentage
    for zone in coordinator.data.zones:
        entities.append(AirTouch3DamperSensor(coordinator, zone.zone_number))

    # Touchpad temperatures
    for touchpad in coordinator.data.touchpads:
        entities.append(AirTouch3TemperatureSensor(coordinator, "touchpad", touchpad.touchpad_number - 1))

    # Wireless sensors (create for all slots so availability updates)
    for index in range(len(coordinator.data.sensors)):
        entities.append(AirTouch3TemperatureSensor(coordinator, "wireless", index))

    async_add_entities(entities)


class AirTouch3TemperatureSensor(CoordinatorEntity[AirTouch3Coordinator], SensorEntity):
    """Temperature sensor for AC, touchpad, or wireless sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: AirTouch3Coordinator, kind: str, index: int) -> None:
        """Initialize temperature sensor."""
        super().__init__(coordinator)
        self.kind = kind
        self.index = index
        self._attr_has_entity_name = True
        if kind == "ac":
            name = coordinator.data.ac_units[index].name
            self._attr_name = f"{name} Temperature"
        elif kind == "touchpad":
            self._attr_name = f"Touchpad {index + 1} Temperature"
        else:
            self._attr_name = f"Wireless Sensor {index + 1} Temperature"

    @property
    def native_value(self) -> float | None:
        """Return temperature value."""
        if self.kind == "ac":
            value = self.coordinator.data.ac_units[self.index].room_temp
            return float(value)

        if self.kind == "touchpad":
            touchpad = self.coordinator.data.touchpads[self.index]
            return float(touchpad.temperature) if touchpad.temperature is not None else None

        sensor = self.coordinator.data.sensors[self.index]
        if not sensor.available:
            return None
        return float(sensor.temperature)

    @property
    def available(self) -> bool:
        """Return availability."""
        if self.kind == "wireless":
            return self.coordinator.data.sensors[self.index].available
        if self.kind == "touchpad":
            return self.coordinator.data.touchpads[self.index].temperature is not None
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes."""
        if self.kind == "wireless":
            sensor = self.coordinator.data.sensors[self.index]
            return {"low_battery": sensor.low_battery}
        if self.kind == "touchpad":
            touchpad = self.coordinator.data.touchpads[self.index]
            return {"assigned_zone": touchpad.assigned_zone}
        return {}

    @property
    def unique_id(self) -> str:
        """Return unique ID."""
        base = self.coordinator.data.device_id
        if self.kind == "ac":
            return f"{base}_ac_{self.index}_temperature"
        if self.kind == "touchpad":
            return f"{base}_touchpad_{self.index + 1}_temperature"
        return f"{base}_wireless_{self.index + 1}_temperature"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.data.device_id)},
            name=self.coordinator.data.system_name,
            manufacturer="Polyaire",
            model="AirTouch 3",
        )


class AirTouch3DamperSensor(CoordinatorEntity[AirTouch3Coordinator], SensorEntity):
    """Damper percentage sensor for a zone."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_has_entity_name = True

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize damper sensor."""
        super().__init__(coordinator)
        self.zone_number = zone_number
        self._attr_name = f"{coordinator.data.zones[zone_number].name} Damper"

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
        """Device registry info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.data.device_id)},
            name=self.coordinator.data.system_name,
            manufacturer="Polyaire",
            model="AirTouch 3",
        )
