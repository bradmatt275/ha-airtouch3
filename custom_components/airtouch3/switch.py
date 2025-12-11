"""Zone switch entities for AirTouch 3."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AirTouch3Coordinator
from .models import ZoneState


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up zone switch entities."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [AirTouch3ZoneSwitch(coordinator, zone.zone_number) for zone in coordinator.data.zones]
    async_add_entities(entities)


class AirTouch3ZoneSwitch(CoordinatorEntity[AirTouch3Coordinator], SwitchEntity):
    """Switch for an AirTouch 3 zone."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AirTouch3Coordinator, zone_number: int) -> None:
        """Initialize zone switch."""
        super().__init__(coordinator)
        self.zone_number = zone_number
        self._attr_name = coordinator.data.zones[zone_number].name

    @property
    def _zone_state(self) -> ZoneState:
        return self.coordinator.data.zones[self.zone_number]

    @property
    def is_on(self) -> bool:
        """Return True if zone is on."""
        return self._zone_state.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn zone on, handling toggle protocol."""
        if not self._zone_state.is_on:
            await self.coordinator.client.zone_toggle(self._zone_state.data_index)
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn zone off, handling toggle protocol."""
        if self._zone_state.is_on:
            await self.coordinator.client.zone_toggle(self._zone_state.data_index)
            await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Additional attributes."""
        zone = self._zone_state
        return {
            "damper_percent": zone.damper_percent,
            "is_spill": zone.is_spill,
            "active_program": zone.active_program,
            "sensor_source": zone.sensor_source,
        }

    @property
    def unique_id(self) -> str:
        """Unique ID for zone."""
        return f"{self.coordinator.data.device_id}_zone_{self.zone_number}"

    @property
    def device_info(self) -> DeviceInfo:
        """Device registry info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.data.device_id)},
            name=self.coordinator.data.system_name,
            manufacturer="Polyaire",
            model="AirTouch 3",
        )
