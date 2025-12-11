"""Config flow for AirTouch 3 integration."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import voluptuous as vol

from .client import AirTouch3Client
from .const import (
    DEFAULT_INCLUDE_SENSORS,
    DEFAULT_INCLUDE_ZONES,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    CONF_INCLUDE_SENSORS,
    CONF_INCLUDE_ZONES,
)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class AirTouch3ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AirTouch 3."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._discovered_device: dict | None = None

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle user step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = AirTouch3Client(
                user_input[CONF_HOST], user_input.get(CONF_PORT, DEFAULT_PORT)
            )
            try:
                if await client.connect():
                    state = await client.get_state()
                    if state:
                        await self.async_set_unique_id(state.device_id)
                        self._abort_if_unique_id_configured()

                        return self.async_create_entry(
                            title=state.system_name,
                            data={
                                CONF_HOST: user_input[CONF_HOST],
                                CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
                            },
                            options={
                                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                                CONF_INCLUDE_SENSORS: DEFAULT_INCLUDE_SENSORS,
                                CONF_INCLUDE_ZONES: DEFAULT_INCLUDE_ZONES,
                            },
                        )
                    errors["base"] = "no_state"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            finally:
                await client.disconnect()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        """Handle reconfigure flow."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None

        if user_input is not None:
            client = AirTouch3Client(
                user_input[CONF_HOST], user_input.get(CONF_PORT, DEFAULT_PORT)
            )
            try:
                if await client.connect():
                    state = await client.get_state()
                    if state is None:
                        errors["base"] = "no_state"
                    elif state.device_id != entry.unique_id:
                        errors["base"] = "different_device"
                    else:
                        return self.async_update_reload_and_abort(
                            entry,
                            data={
                                CONF_HOST: user_input[CONF_HOST],
                                CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
                            },
                        )
                else:
                    errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            finally:
                await client.disconnect()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str,
                    vol.Optional(CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)): int,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return AirTouch3OptionsFlow(config_entry)


class AirTouch3OptionsFlow(config_entries.OptionsFlow):
    """Handle AirTouch 3 options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Store reference to config entry."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Handle options step."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                    vol.Optional(
                        CONF_INCLUDE_SENSORS,
                        default=options.get(CONF_INCLUDE_SENSORS, DEFAULT_INCLUDE_SENSORS),
                    ): bool,
                    vol.Optional(
                        CONF_INCLUDE_ZONES,
                        default=options.get(CONF_INCLUDE_ZONES, DEFAULT_INCLUDE_ZONES),
                    ): bool,
                }
            ),
        )
