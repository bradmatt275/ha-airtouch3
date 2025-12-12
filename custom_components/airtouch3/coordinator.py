"""Data update coordinator for AirTouch 3."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import AirTouch3Client
from .const import DEFAULT_SCAN_INTERVAL
from .models import SystemState

LOGGER = logging.getLogger(__name__)

# Optimistic hold period for control mode toggle
CONTROL_MODE_OPTIMISTIC_HOLD_SECONDS = 5.0


class AirTouch3Coordinator(DataUpdateCoordinator[SystemState]):
    """Coordinator managing connection and state polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AirTouch3Client,
        name: str,
        update_interval: timedelta | None = None,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=name,
            config_entry=config_entry,
            update_interval=update_interval or timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        # Track optimistic control mode states: {zone_number: (expected_state, expiry_time)}
        self._optimistic_control_modes: dict[int, tuple[bool, float]] = {}

    def set_optimistic_control_mode(self, zone_number: int, expected_state: bool) -> None:
        """Set optimistic control mode state for a zone."""
        self._optimistic_control_modes[zone_number] = (
            expected_state,
            time.monotonic() + CONTROL_MODE_OPTIMISTIC_HOLD_SECONDS,
        )
        # Trigger UI update
        self.async_set_updated_data(self.data)

    def get_zone_control_mode(self, zone_number: int) -> bool:
        """Get zone control mode, considering optimistic state.

        Returns True for temperature mode, False for percentage (fan) mode.
        """
        # Check if we have an active optimistic state
        if zone_number in self._optimistic_control_modes:
            expected_state, expiry_time = self._optimistic_control_modes[zone_number]
            if time.monotonic() < expiry_time:
                # Still within hold period - return optimistic state
                return expected_state
            else:
                # Expired - clean up
                del self._optimistic_control_modes[zone_number]

        # Return actual state from data
        return self.data.zones[zone_number].temperature_control

    def _check_optimistic_states(self) -> None:
        """Clean up expired optimistic states and check for confirmation."""
        now = time.monotonic()
        expired = []
        for zone_number, (expected_state, expiry_time) in self._optimistic_control_modes.items():
            if now >= expiry_time:
                expired.append(zone_number)
            elif self.data.zones[zone_number].temperature_control == expected_state:
                # Actual state now matches expected - can clear early
                expired.append(zone_number)
        for zone_number in expired:
            del self._optimistic_control_modes[zone_number]

    async def _async_setup(self) -> None:
        """Run once before first refresh to establish connection."""
        if not await self.client.connect():
            raise UpdateFailed("Cannot connect to device")

    async def _async_update_data(self) -> SystemState:
        """Fetch latest state from device."""
        try:
            if not self.client.connected:
                if not await self.client.connect():
                    raise UpdateFailed("Cannot connect to device")

            # Always fetch fresh state instead of returning cached
            state = await self.client.refresh_state()
            if state is None:
                raise UpdateFailed("No state received")

            # Clean up expired optimistic states after getting fresh data
            # This is called after self.data is updated
            return state
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"Timeout while updating: {err}") from err
        except OSError as err:
            raise UpdateFailed(f"Communication error: {err}") from err

    def async_set_updated_data(self, data: SystemState) -> None:
        """Update data and check optimistic states."""
        super().async_set_updated_data(data)
        self._check_optimistic_states()

    async def async_shutdown(self) -> None:
        """Close TCP connection on unload."""
        await self.client.disconnect()
