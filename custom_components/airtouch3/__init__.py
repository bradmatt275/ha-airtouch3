"""AirTouch 3 integration setup."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant

from .client import AirTouch3Client
from .const import (
    CONF_INCLUDE_SENSORS,
    CONF_INCLUDE_ZONES,
    DEFAULT_INCLUDE_SENSORS,
    DEFAULT_INCLUDE_ZONES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import AirTouch3Coordinator

PLATFORMS: list[Platform] = []
LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AirTouch 3 from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = AirTouch3Client(entry.data[CONF_HOST], entry.data.get(CONF_PORT, 8899))
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    include_sensors = entry.options.get(CONF_INCLUDE_SENSORS, DEFAULT_INCLUDE_SENSORS)
    include_zones = entry.options.get(CONF_INCLUDE_ZONES, DEFAULT_INCLUDE_ZONES)

    coordinator = AirTouch3Coordinator(
        hass,
        client,
        name=f"AirTouch 3 ({entry.data[CONF_HOST]})",
        update_interval=timedelta(seconds=scan_interval),
        config_entry=entry,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Always include switch (for AC power and zones) and select (for AC mode/fan)
    platforms = [Platform.SWITCH, Platform.SELECT]
    if include_sensors:
        platforms.append(Platform.SENSOR)

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: AirTouch3Coordinator = hass.data[DOMAIN][entry.entry_id]
    platforms = [Platform.SWITCH, Platform.SELECT]
    if entry.options.get(CONF_INCLUDE_SENSORS, DEFAULT_INCLUDE_SENSORS):
        platforms.append(Platform.SENSOR)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        await coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading entry."""
    await hass.config_entries.async_reload(entry.entry_id)
