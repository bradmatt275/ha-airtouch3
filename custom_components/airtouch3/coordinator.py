"""Data update coordinator for AirTouch 3."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import AirTouch3Client
from .const import DEFAULT_SCAN_INTERVAL
from .models import SystemState

LOGGER = logging.getLogger(__name__)


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

            return state
        except asyncio.TimeoutError as err:
            raise UpdateFailed(f"Timeout while updating: {err}") from err
        except OSError as err:
            raise UpdateFailed(f"Communication error: {err}") from err

    async def async_shutdown(self) -> None:
        """Close TCP connection on unload."""
        await self.client.disconnect()
