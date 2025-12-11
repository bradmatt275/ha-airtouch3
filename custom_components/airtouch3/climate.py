"""Climate entities for AirTouch 3 AC units."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_TEMP, MIN_TEMP, TEMP_STEP
from .coordinator import AirTouch3Coordinator
from .models import AcMode, AcState, FanSpeed

HA_MODE_MAP = {
    AcMode.AUTO: HVACMode.AUTO,
    AcMode.HEAT: HVACMode.HEAT,
    AcMode.COOL: HVACMode.COOL,
    AcMode.DRY: HVACMode.DRY,
    AcMode.FAN: HVACMode.FAN_ONLY,
}

HA_FAN_MAP = {
    FanSpeed.AUTO: "auto",
    FanSpeed.QUIET: "quiet",
    FanSpeed.LOW: "low",
    FanSpeed.MEDIUM: "medium",
    FanSpeed.HIGH: "high",
    FanSpeed.POWERFUL: "powerful",
}

REVERSE_FAN_MAP = {v: k for k, v in HA_FAN_MAP.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up climate entities from config entry."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [AirTouch3Climate(coordinator, ac_state.ac_number) for ac_state in coordinator.data.ac_units]
    async_add_entities(entities)


class AirTouch3Climate(CoordinatorEntity[AirTouch3Coordinator], ClimateEntity):
    """Representation of an AirTouch 3 AC unit."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = TEMP_STEP
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP

    def __init__(self, coordinator: AirTouch3Coordinator, ac_number: int) -> None:
        """Initialize entity."""
        super().__init__(coordinator)
        self.ac_number = ac_number
        self._attr_name = coordinator.data.ac_units[ac_number].name

    @property
    def _ac_state(self) -> AcState:
        return self.coordinator.data.ac_units[self.ac_number]

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return supported HVAC modes."""
        return [HVACMode.OFF, HVACMode.AUTO, HVACMode.HEAT, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY]

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current mode."""
        ac = self._ac_state
        if not ac.power_on:
            return HVACMode.OFF
        return HA_MODE_MAP.get(ac.mode, HVACMode.AUTO)

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current HVAC action."""
        ac = self._ac_state
        if not ac.power_on:
            return HVACAction.OFF
        if ac.mode == AcMode.HEAT:
            return HVACAction.HEATING
        if ac.mode == AcMode.COOL:
            return HVACAction.COOLING
        if ac.mode == AcMode.DRY:
            return HVACAction.DRYING
        if ac.mode == AcMode.FAN:
            return HVACAction.FAN
        return HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        """Return current temperature."""
        return float(self._ac_state.room_temp)

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        return float(self._ac_state.setpoint)

    @property
    def fan_modes(self) -> list[str]:
        """Return list of available fan modes."""
        return [HA_FAN_MAP[speed] for speed in self._ac_state.supported_fan_speeds]

    @property
    def fan_mode(self) -> str | None:
        """Return current fan mode."""
        return HA_FAN_MAP.get(self._ac_state.fan_speed)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        ac = self._ac_state
        if hvac_mode == HVACMode.OFF:
            if ac.power_on:
                await self.coordinator.client.ac_power_toggle(self.ac_number)
                await self.coordinator.async_request_refresh()
            return

        # Ensure device is on before setting mode
        if not ac.power_on:
            await self.coordinator.client.ac_power_toggle(self.ac_number)

        target_mode = self._hvac_to_ac_mode(hvac_mode)
        await self.coordinator.client.ac_set_mode(self.ac_number, target_mode)
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        if ATTR_TEMPERATURE not in kwargs:
            return
        temperature = int(kwargs[ATTR_TEMPERATURE])
        await self.coordinator.client.ac_set_temperature(self.ac_number, temperature)
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode."""
        speed = REVERSE_FAN_MAP.get(fan_mode)
        if speed is None:
            return
        await self.coordinator.client.ac_set_fan_speed(self.ac_number, speed)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn AC on."""
        if not self._ac_state.power_on:
            await self.coordinator.client.ac_power_toggle(self.ac_number)
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn AC off."""
        if self._ac_state.power_on:
            await self.coordinator.client.ac_power_toggle(self.ac_number)
            await self.coordinator.async_request_refresh()

    @property
    def unique_id(self) -> str:
        """Return unique ID for entity."""
        return f"{self.coordinator.data.device_id}_ac_{self.ac_number}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.data.device_id)},
            name=self.coordinator.data.system_name,
            manufacturer="Polyaire",
            model="AirTouch 3",
        )

    def _hvac_to_ac_mode(self, hvac_mode: HVACMode) -> AcMode:
        """Map HA HVAC mode to protocol mode."""
        mapping = {
            HVACMode.AUTO: AcMode.AUTO,
            HVACMode.HEAT: AcMode.HEAT,
            HVACMode.COOL: AcMode.COOL,
            HVACMode.DRY: AcMode.DRY,
            HVACMode.FAN_ONLY: AcMode.FAN,
        }
        return mapping.get(hvac_mode, AcMode.AUTO)
