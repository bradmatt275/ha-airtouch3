"""Select entities for AirTouch 3."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AirTouch3Coordinator
from .models import AcMode, AcState, FanSpeed
from .switch import get_main_device_info, get_zone_device_info

# Ignore coordinator updates for this many seconds after a command
OPTIMISTIC_HOLD_SECONDS = 5.0

# Mode mappings
MODE_TO_STR = {
    AcMode.AUTO: "Auto",
    AcMode.HEAT: "Heat",
    AcMode.DRY: "Dry",
    AcMode.FAN: "Fan",
    AcMode.COOL: "Cool",
}
STR_TO_MODE = {v: k for k, v in MODE_TO_STR.items()}

# Fan speed mappings
FAN_TO_STR = {
    FanSpeed.AUTO: "Auto",
    FanSpeed.QUIET: "Quiet",
    FanSpeed.LOW: "Low",
    FanSpeed.MEDIUM: "Medium",
    FanSpeed.HIGH: "High",
    FanSpeed.POWERFUL: "Powerful",
}
STR_TO_FAN = {v: k for k, v in FAN_TO_STR.items()}

# Zone control mode options
ZONE_CONTROL_MODE_FAN = "Fan"
ZONE_CONTROL_MODE_TEMPERATURE = "Temperature"
ZONE_CONTROL_MODE_OPTIONS = [ZONE_CONTROL_MODE_FAN, ZONE_CONTROL_MODE_TEMPERATURE]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up select entities."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = []

    for ac in coordinator.data.ac_units:
        entities.append(AirTouch3AcModeSelect(coordinator, ac.ac_number))
        entities.append(AirTouch3AcFanSelect(coordinator, ac.ac_number))

    # Zone control mode selects (for all zones - availability based on has_sensor)
    for zone in coordinator.data.zones:
        entities.append(AirTouch3ZoneControlModeSelect(coordinator, zone.zone_number))

    async_add_entities(entities)


class AirTouch3AcModeSelect(CoordinatorEntity[AirTouch3Coordinator], SelectEntity):
    """Select entity for AC mode."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AirTouch3Coordinator, ac_number: int) -> None:
        """Initialize AC mode select."""
        super().__init__(coordinator)
        self.ac_number = ac_number
        ac_name = coordinator.data.ac_units[ac_number].name
        self._attr_name = f"{ac_name} Mode"
        self._attr_options = list(MODE_TO_STR.values())
        self._optimistic_mode: AcMode | None = None
        self._optimistic_until: float = 0.0

    @property
    def _ac_state(self) -> AcState:
        return self.coordinator.data.ac_units[self.ac_number]

    @property
    def current_option(self) -> str | None:
        """Return current mode."""
        if self._optimistic_mode is not None and time.monotonic() < self._optimistic_until:
            return MODE_TO_STR.get(self._optimistic_mode)
        self._optimistic_mode = None
        return MODE_TO_STR.get(self._ac_state.mode)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        if self._optimistic_mode is not None:
            if time.monotonic() >= self._optimistic_until:
                self._optimistic_mode = None
            elif self._ac_state.mode == self._optimistic_mode:
                self._optimistic_mode = None
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        """Change the AC mode."""
        mode = STR_TO_MODE.get(option)
        if mode is None:
            return
        self._optimistic_mode = mode
        self._optimistic_until = time.monotonic() + OPTIMISTIC_HOLD_SECONDS
        self.async_write_ha_state()
        await self.coordinator.client.ac_set_mode(self.ac_number, mode)
        await self.coordinator.async_request_refresh()

    @property
    def unique_id(self) -> str:
        """Unique ID for AC mode select."""
        return f"{self.coordinator.data.device_id}_ac_{self.ac_number}_mode"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - main device."""
        return get_main_device_info(self.coordinator)


class AirTouch3AcFanSelect(CoordinatorEntity[AirTouch3Coordinator], SelectEntity):
    """Select entity for AC fan speed."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AirTouch3Coordinator, ac_number: int) -> None:
        """Initialize AC fan select."""
        super().__init__(coordinator)
        self.ac_number = ac_number
        ac_name = coordinator.data.ac_units[ac_number].name
        self._attr_name = f"{ac_name} Fan Speed"
        self._optimistic_fan: FanSpeed | None = None
        self._optimistic_until: float = 0.0

    @property
    def _ac_state(self) -> AcState:
        return self.coordinator.data.ac_units[self.ac_number]

    @property
    def options(self) -> list[str]:
        """Return available fan speed options based on AC capabilities."""
        return [FAN_TO_STR[speed] for speed in self._ac_state.supported_fan_speeds]

    @property
    def current_option(self) -> str | None:
        """Return current fan speed."""
        if self._optimistic_fan is not None and time.monotonic() < self._optimistic_until:
            return FAN_TO_STR.get(self._optimistic_fan)
        self._optimistic_fan = None
        return FAN_TO_STR.get(self._ac_state.fan_speed)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        if self._optimistic_fan is not None:
            if time.monotonic() >= self._optimistic_until:
                self._optimistic_fan = None
            elif self._ac_state.fan_speed == self._optimistic_fan:
                self._optimistic_fan = None
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        """Change the fan speed."""
        speed = STR_TO_FAN.get(option)
        if speed is None:
            return
        self._optimistic_fan = speed
        self._optimistic_until = time.monotonic() + OPTIMISTIC_HOLD_SECONDS
        self.async_write_ha_state()
        await self.coordinator.client.ac_set_fan_speed(self.ac_number, speed)
        await self.coordinator.async_request_refresh()

    @property
    def unique_id(self) -> str:
        """Unique ID for AC fan select."""
        return f"{self.coordinator.data.device_id}_ac_{self.ac_number}_fan"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - main device."""
        return get_main_device_info(self.coordinator)


class AirTouch3ZoneControlModeSelect(CoordinatorEntity[AirTouch3Coordinator], SelectEntity):
    """Select entity for zone control mode (Temperature or Fan/%).

    Only available for zones that have a temperature sensor assigned.
    Uses optimistic updates - when a selection is made, the state
    immediately shows the expected new value, reverting after timeout if
    the actual state doesn't change.
    """

    _attr_has_entity_name = True
    _attr_name = "Control Mode"

    # Class-level registry for optimistic mode values, shared with setpoint sensor.
    # Maps (device_id, zone_number) -> (is_temp_mode, timestamp)
    _optimistic_modes: dict[tuple[str, int], tuple[bool, float]] = {}

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize zone control mode select."""
        super().__init__(coordinator)
        self.zone_number = zone_number
        self._attr_options = ZONE_CONTROL_MODE_OPTIONS
        
        # Disable entity by default if zone doesn't have a sensor at startup.
        # This hides it from the UI for zones that will never have sensors.
        # For zones with wireless sensors not yet detected, the entity will
        # become available once the sensor transmits (via sticky detection).
        zone = coordinator.data.zones[zone_number]
        if not zone.has_sensor:
            self._attr_entity_registry_enabled_default = False

    @classmethod
    def set_optimistic_mode(cls, device_id: str, zone_number: int, is_temp_mode: bool) -> None:
        """Set an optimistic mode value (shared with setpoint sensor)."""
        cls._optimistic_modes[(device_id, zone_number)] = (is_temp_mode, time.monotonic())

    @classmethod
    def clear_optimistic_mode(cls, device_id: str, zone_number: int) -> None:
        """Clear the optimistic mode value."""
        cls._optimistic_modes.pop((device_id, zone_number), None)

    @classmethod
    def get_optimistic_mode(cls, device_id: str, zone_number: int) -> bool | None:
        """Get the current optimistic mode if set and not expired."""
        entry = cls._optimistic_modes.get((device_id, zone_number))
        if entry is None:
            return None
        is_temp_mode, timestamp = entry
        # Check if expired (use same timeout as other optimistic values)
        if time.monotonic() - timestamp > OPTIMISTIC_HOLD_SECONDS:
            cls._optimistic_modes.pop((device_id, zone_number), None)
            return None
        return is_temp_mode

    @property
    def _optimistic_key(self) -> tuple[str, int]:
        """Get the key for optimistic mode lookup."""
        return (self.coordinator.data.device_id, self.zone_number)

    @property
    def available(self) -> bool:
        """Return True if zone has a temperature sensor."""
        return self.coordinator.data.zones[self.zone_number].has_sensor

    @property
    def current_option(self) -> str | None:
        """Return current control mode."""
        # Check optimistic state first
        optimistic = self.get_optimistic_mode(*self._optimistic_key)
        if optimistic is not None:
            return ZONE_CONTROL_MODE_TEMPERATURE if optimistic else ZONE_CONTROL_MODE_FAN
        # Get actual state from coordinator
        is_temp_mode = self.coordinator.data.zones[self.zone_number].temperature_control
        return ZONE_CONTROL_MODE_TEMPERATURE if is_temp_mode else ZONE_CONTROL_MODE_FAN

    @property
    def icon(self) -> str:
        """Return icon based on current mode."""
        current = self.current_option
        return "mdi:thermometer" if current == ZONE_CONTROL_MODE_TEMPERATURE else "mdi:fan"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator."""
        optimistic = self.get_optimistic_mode(*self._optimistic_key)
        if optimistic is not None:
            actual_mode = self.coordinator.data.zones[self.zone_number].temperature_control
            if actual_mode == optimistic:
                # Actual state matches expected, clear optimistic state
                self.clear_optimistic_mode(*self._optimistic_key)
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        """Change the zone control mode."""
        target_is_temp = option == ZONE_CONTROL_MODE_TEMPERATURE
        current_is_temp = self.coordinator.data.zones[self.zone_number].temperature_control

        # Only send toggle if we need to change the mode
        if target_is_temp != current_is_temp:
            self.set_optimistic_mode(*self._optimistic_key, target_is_temp)
            # Trigger update for this entity and the setpoint sensor
            self.async_write_ha_state()
            self.coordinator.async_set_updated_data(self.coordinator.data)
            await self.coordinator.client.zone_toggle_mode(self.zone_number)
            await self.coordinator.async_request_refresh()

    @property
    def unique_id(self) -> str:
        """Unique ID for zone control mode select."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}_control_mode"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info - zone sub-device."""
        return get_zone_device_info(self.coordinator, self.zone_number)
