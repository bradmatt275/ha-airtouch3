# AirTouch 3 Home Assistant Integration - Technical Design Document

## 1. Overview

### 1.1 Purpose
Build a native Home Assistant custom integration for the Polyaire AirTouch 3 air conditioning control system. The integration communicates with the AirTouch 3 device over the local network using a reverse-engineered binary TCP protocol.

### 1.2 Goals
- Expose AC units as Home Assistant Climate entities with full control (power, temperature, mode, fan speed)
- Expose zones as Switch entities with damper control
- Expose temperature sensors (wireless sensors, touchpads) as Sensor entities
- Provide a user-friendly config flow for setup
- Support multiple AirTouch 3 devices
- Handle connection resilience and automatic reconnection

### 1.3 Reference Documentation
- `PROTOCOL_DOCUMENTATION.md` - Complete protocol specification (attached to project)
- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- [Home Assistant Climate Entity](https://developers.home-assistant.io/docs/core/entity/climate/)

---

## 2. Architecture

### 2.1 High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Home Assistant                               │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    AirTouch 3 Integration                       │ │
│  │                                                                  │ │
│  │  ┌──────────────┐    ┌─────────────────────────────────────┐   │ │
│  │  │ Config Flow  │    │      DataUpdateCoordinator          │   │ │
│  │  │              │    │  - Manages polling interval          │   │ │
│  │  │ - Discovery  │    │  - Distributes state to entities     │   │ │
│  │  │ - Manual IP  │    │  - Handles update scheduling         │   │ │
│  │  └──────────────┘    └──────────────┬──────────────────────┘   │ │
│  │                                      │                          │ │
│  │                                      ▼                          │ │
│  │                      ┌───────────────────────────┐              │ │
│  │                      │    AirTouch3Client        │              │ │
│  │                      │  - Async TCP connection   │              │ │
│  │                      │  - Message framing        │              │ │
│  │                      │  - Command encoding       │              │ │
│  │                      │  - State parsing          │              │ │
│  │                      └──────────────┬────────────┘              │ │
│  │                                      │                          │ │
│  │  ┌─────────────┬─────────────┬──────┴────┬─────────────┐       │ │
│  │  ▼             ▼             ▼           ▼             ▼       │ │
│  │ Climate    Climate       Switch      Switch        Sensor      │ │
│  │ (AC1)      (AC2)        (Zone 0)    (Zone 1)    (Temp Sensor)  │ │
│  │                            ...         ...          ...        │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ TCP Port 8899
                                    ▼
                          ┌─────────────────┐
                          │  AirTouch 3     │
                          │  Device         │
                          └─────────────────┘
```

### 2.2 File Structure

```
custom_components/
└── airtouch3/
    ├── __init__.py           # Integration setup, platform loading
    ├── manifest.json         # Integration metadata
    ├── const.py              # Constants (commands, offsets, defaults)
    ├── config_flow.py        # UI configuration flow
    ├── coordinator.py        # DataUpdateCoordinator
    ├── climate.py            # Climate entities (AC units)
    ├── switch.py             # Switch entities (zones)
    ├── sensor.py             # Sensor entities (temperatures)
    ├── models.py             # Data classes for parsed state
    ├── client.py             # AirTouch3Client (TCP protocol)
    ├── strings.json          # UI strings (English)
    └── translations/
        └── en.json           # Translations
```

---

## 3. Component Specifications

### 3.1 `const.py` - Constants

Define all protocol constants, configuration defaults, and byte offsets.

```python
# Key constants to define:

DOMAIN = "airtouch3"
DEFAULT_PORT = 8899
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 1.0
SCAN_INTERVAL = 30  # seconds between polls (device sends state after commands anyway)

# Message structure
MSG_HEADER = 0x55
MSG_LENGTH = 0x0C
STATE_MSG_SIZE = 492
COMMAND_MSG_SIZE = 13

# Command bytes (byte 1)
CMD_INIT = 0x01
CMD_ZONE = 0x81
CMD_AC = 0x86

# AC sub-commands (byte 4)
AC_POWER_TOGGLE = 0x80
AC_MODE = 0x81
AC_FAN = 0x82
AC_TEMP_UP = 0xA3
AC_TEMP_DOWN = 0x93

# Zone sub-commands
ZONE_TOGGLE = 0x80
ZONE_DAMPER_UP = 0x02
ZONE_DAMPER_DOWN = 0x01

# State message byte offsets (from PROTOCOL_DOCUMENTATION.md)
# Document ALL offsets here for maintainability

# Brand IDs requiring mode remapping
BRAND_REMAP_11 = 11
BRAND_REMAP_15 = 15
BRAND_SPECIAL_FAN = 2
```

### 3.2 `models.py` - Data Classes

Define typed data structures for parsed device state.

```python
from dataclasses import dataclass, field
from enum import IntEnum

class AcMode(IntEnum):
    """AC operating modes."""
    AUTO = 0
    HEAT = 1
    DRY = 2
    FAN = 3
    COOL = 4

class FanSpeed(IntEnum):
    """Fan speed levels."""
    AUTO = 0
    QUIET = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    POWERFUL = 5

@dataclass
class AcState:
    """State of a single AC unit."""
    ac_number: int  # 0 or 1
    name: str
    power_on: bool
    mode: AcMode
    fan_speed: FanSpeed
    setpoint: int  # Target temperature °C
    room_temp: int  # Current temperature °C
    brand_id: int
    has_error: bool
    error_code: int
    supported_fan_speeds: list[FanSpeed]
    # Control mode: 0=not available, 1=basic, 2=full
    control_mode: int

@dataclass
class ZoneState:
    """State of a single zone."""
    zone_number: int
    name: str
    is_on: bool
    is_spill: bool
    damper_percent: int  # 0-100
    active_program: int  # 0=none, 1-4=program number
    setpoint: int | None  # Zone setpoint if available
    sensor_source: int  # Temperature sensor assignment

@dataclass
class SensorState:
    """State of a wireless temperature sensor."""
    sensor_number: int
    available: bool
    low_battery: bool
    temperature: int

@dataclass
class TouchpadState:
    """State of a touchpad."""
    touchpad_number: int  # 1 or 2
    assigned_zone: int
    temperature: int

@dataclass
class SystemState:
    """Complete system state parsed from 492-byte message."""
    raw_data: bytes
    device_id: str
    system_name: str
    zone_count: int
    is_dual_ducted: bool
    ac_units: list[AcState]
    zones: list[ZoneState]
    sensors: list[SensorState]
    touchpads: list[TouchpadState]
```

### 3.3 `client.py` - Protocol Client

Async TCP client implementing the AirTouch 3 protocol.

#### Class: `AirTouch3Client`

```python
class AirTouch3Client:
    """Async client for AirTouch 3 device communication."""
    
    def __init__(self, host: str, port: int = 8899):
        """Initialize client with device address."""
        
    async def connect(self) -> bool:
        """
        Establish TCP connection and send init message.
        
        Flow:
        1. Create async socket connection with 5s timeout
        2. Send 13-byte init message
        3. Wait for 492-byte state response
        4. Parse and store initial state
        5. Return success/failure
        
        Must handle:
        - Connection timeout
        - Connection refused
        - Init message failure
        """
        
    async def disconnect(self) -> None:
        """Close TCP connection gracefully."""
        
    async def get_state(self) -> SystemState | None:
        """
        Get current system state.
        
        If connected and state is fresh, return cached state.
        Otherwise, wait for next state message from device.
        """
        
    # AC Control Methods
    async def ac_power_toggle(self, ac_num: int) -> bool:
        """Toggle AC unit power. Returns success."""
        
    async def ac_set_mode(self, ac_num: int, mode: AcMode) -> bool:
        """
        Set AC operating mode.
        
        IMPORTANT: Must handle brand-specific mode remapping:
        - Brand 11: Modes remapped (0→0, 1→2, 2→3, 3→4, 4→1)
        - Brand 15: Modes remapped (0→5, 1→2, 2→3, 3→4, 4→1)
        - Others: Use mode value directly
        """
        
    async def ac_set_fan_speed(self, ac_num: int, speed: FanSpeed) -> bool:
        """
        Set AC fan speed.
        
        Must handle:
        - Brand 2 with supported_speed=4: values offset by 1
        - Brand 15: Auto = value 4
        - Check supported_fan_speeds before sending
        """
        
    async def ac_temp_up(self, ac_num: int) -> bool:
        """Increase setpoint by 1°C."""
        
    async def ac_temp_down(self, ac_num: int) -> bool:
        """Decrease setpoint by 1°C."""
        
    async def ac_set_temperature(self, ac_num: int, target: int) -> bool:
        """
        Set target temperature.
        
        IMPORTANT: Protocol only supports increment/decrement.
        Implementation must:
        1. Read current setpoint from state
        2. Calculate difference
        3. Loop sending temp_up or temp_down commands
        4. Verify final setpoint matches target
        5. Respect min/max limits (typically 16-30°C)
        """
        
    # Zone Control Methods
    async def zone_toggle(self, zone_num: int) -> bool:
        """Toggle zone on/off."""
        
    async def zone_set_damper(self, zone_num: int, target_percent: int) -> bool:
        """
        Set zone damper opening percentage.
        
        Similar to temperature - must loop with damper_up/down commands.
        Damper values are in 5% increments (0, 5, 10, ... 100).
        """
```

#### Internal Methods

```python
    def _calculate_checksum(self, message: bytes) -> int:
        """
        Calculate checksum for bytes 0-11.
        checksum = sum(message[0:12]) & 0xFF
        """
        
    def _create_command(self, cmd: int, p1: int = 0, p2: int = 0, p3: int = 0) -> bytes:
        """
        Create 13-byte command message.
        
        Format:
        [0x55, cmd, 0x0C, p1, p2, p3, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, checksum]
        """
        
    async def _send_command(self, command: bytes) -> SystemState | None:
        """
        Send command and wait for state response.
        
        IMPORTANT: Device sends 492-byte state after every command.
        Must read and parse this response.
        """
        
    def _parse_state(self, data: bytes) -> SystemState:
        """
        Parse 492-byte state message into SystemState.
        
        See PROTOCOL_DOCUMENTATION.md "State Message Structure" section
        for complete byte map.
        
        Key parsing tasks:
        - Extract zone names (bytes 104-231)
        - Parse zone status (bytes 232-247)
        - Parse zone damper (bytes 248-263)
        - Parse AC status (bytes 423-424)
        - Parse AC brands (bytes 425-426)
        - Parse AC modes (bytes 427-428) with brand remapping
        - Parse AC fan speeds (bytes 429-430)
        - Parse AC setpoints (bytes 431-432)
        - Parse AC room temps (bytes 433-434)
        - Parse wireless sensors (bytes 451-482)
        - Extract device ID (bytes 483-490, low nibbles)
        """
```

#### Message Buffering

```python
class MessageBuffer:
    """
    Buffer TCP stream into complete messages.
    
    TCP does not guarantee message boundaries. Must accumulate
    bytes and extract complete 492-byte state messages.
    
    Also handle 395-byte "internet mode" responses (detect by
    checking if bytes 100-107 are all zero) - these should be
    skipped in local mode.
    """
    
    def __init__(self):
        self.buffer = bytearray()
        
    def add_data(self, data: bytes) -> list[bytes]:
        """
        Add received data and return list of complete messages.
        
        Logic:
        1. Append data to buffer
        2. While buffer >= 492 bytes:
           - Extract 492-byte message
           - Add to results
        3. Check for 395-byte internet responses (bytes 100-107 == 0)
           - Extract and discard these
        4. Return list of complete 492-byte messages
        """
```

### 3.4 `coordinator.py` - Data Update Coordinator

Manages state polling and distribution to entities.

```python
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

class AirTouch3Coordinator(DataUpdateCoordinator[SystemState]):
    """
    Coordinator for AirTouch 3 data updates.
    
    Responsibilities:
    - Maintain persistent connection to device
    - Poll for state updates at regular intervals
    - Handle connection failures and reconnection
    - Distribute state to all entities
    """
    
    def __init__(
        self,
        hass: HomeAssistant,
        client: AirTouch3Client,
        name: str,
    ):
        """Initialize coordinator."""
        super().__init__(
            hass,
            logger,
            name=name,
            update_interval=timedelta(seconds=30),
        )
        self.client = client
        
    async def _async_update_data(self) -> SystemState:
        """
        Fetch latest state from device.
        
        Called by HA at update_interval.
        
        Must handle:
        - Connection not established -> connect first
        - Connection lost -> reconnect
        - Timeout -> raise UpdateFailed
        - Parse errors -> raise UpdateFailed
        """
        
    async def async_shutdown(self) -> None:
        """Disconnect client on HA shutdown."""
```

### 3.5 `climate.py` - Climate Entities

One climate entity per AC unit.

```python
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)

class AirTouch3Climate(CoordinatorEntity, ClimateEntity):
    """Climate entity for AirTouch 3 AC unit."""
    
    # Entity attributes
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_min_temp = 16
    _attr_max_temp = 30
    
    def __init__(
        self,
        coordinator: AirTouch3Coordinator,
        ac_number: int,  # 0 or 1
    ):
        """Initialize climate entity."""
        
    @property
    def supported_features(self) -> ClimateEntityFeature:
        """
        Return supported features.
        
        Should include:
        - TARGET_TEMPERATURE
        - FAN_MODE
        - TURN_ON
        - TURN_OFF
        """
        
    @property
    def hvac_modes(self) -> list[HVACMode]:
        """
        Return supported HVAC modes.
        
        Map AirTouch modes to HA modes:
        - AUTO -> HVACMode.AUTO
        - HEAT -> HVACMode.HEAT
        - COOL -> HVACMode.COOL
        - DRY -> HVACMode.DRY
        - FAN -> HVACMode.FAN_ONLY
        - (when off) -> HVACMode.OFF
        """
        
    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        # Get from coordinator.data.ac_units[self.ac_number]
        
    @property
    def hvac_action(self) -> HVACAction | None:
        """
        Return current HVAC action.
        
        Derive from:
        - Power state (off = HVACAction.OFF)
        - Mode (heating/cooling/drying/fan/idle)
        - Could use byte 360 turbo/spill flags for more accuracy
        """
        
    @property
    def current_temperature(self) -> float | None:
        """Return current room temperature."""
        
    @property
    def target_temperature(self) -> float | None:
        """Return target temperature."""
        
    @property
    def fan_modes(self) -> list[str]:
        """
        Return available fan modes.
        
        Should check supported_fan_speeds from AC state
        and only return those that are supported.
        """
        
    @property
    def fan_mode(self) -> str | None:
        """Return current fan mode."""
        
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """
        Set HVAC mode.
        
        If HVACMode.OFF -> turn off AC
        Otherwise -> turn on AC (if needed) and set mode
        """
        
    async def async_set_temperature(self, **kwargs) -> None:
        """
        Set target temperature.
        
        Call coordinator.client.ac_set_temperature()
        Then request coordinator refresh
        """
        
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode."""
        
    async def async_turn_on(self) -> None:
        """Turn on AC (if off)."""
        
    async def async_turn_off(self) -> None:
        """Turn off AC (if on)."""
        
    @property
    def unique_id(self) -> str:
        """Return unique ID based on device_id and ac_number."""
        # Format: "{device_id}_ac_{ac_number}"
        
    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for device registry."""
```

### 3.6 `switch.py` - Zone Switch Entities

One switch entity per zone for on/off control.

```python
from homeassistant.components.switch import SwitchEntity

class AirTouch3ZoneSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity for AirTouch 3 zone on/off control."""
    
    _attr_has_entity_name = True
    
    def __init__(
        self,
        coordinator: AirTouch3Coordinator,
        zone_number: int,
    ):
        """Initialize zone switch."""
        
    @property
    def is_on(self) -> bool:
        """Return True if zone is on."""
        # Get from coordinator.data.zones[self.zone_number].is_on
        
    async def async_turn_on(self, **kwargs) -> None:
        """
        Turn zone on.
        
        IMPORTANT: Protocol uses toggle, not set.
        Must check current state first:
        - If already on, do nothing
        - If off, send toggle command
        """
        
    async def async_turn_off(self, **kwargs) -> None:
        """Turn zone off (same toggle logic)."""
        
    @property
    def extra_state_attributes(self) -> dict:
        """
        Return additional state attributes.
        
        Include:
        - damper_percent
        - is_spill
        - active_program
        """
        
    @property
    def unique_id(self) -> str:
        """Return unique ID: {device_id}_zone_{zone_number}"""
```

### 3.7 `sensor.py` - Sensor Entities

Temperature sensors for zones, touchpads, and wireless sensors.

```python
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)

class AirTouch3TemperatureSensor(CoordinatorEntity, SensorEntity):
    """Temperature sensor entity."""
    
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    
    # Create variants for:
    # - AC room temperature
    # - Touchpad temperature
    # - Wireless sensor temperature

class AirTouch3DamperSensor(CoordinatorEntity, SensorEntity):
    """Zone damper percentage sensor."""
    
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    
    # Reports damper_percent (0-100)
```

### 3.8 `config_flow.py` - Configuration Flow

User interface for adding the integration. This controls what users see when they:
1. Add the integration for the first time (Config Flow)
2. Click "Configure" on an existing integration (Options Flow)

#### 3.8.1 Configuration Parameters

**Initial Setup Parameters (Config Flow):**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `host` | string | Yes | - | IP address of AirTouch 3 device |
| `port` | integer | No | 8899 | TCP port (rarely needs changing) |

**Runtime Options (Options Flow):**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `scan_interval` | integer | No | 30 | Polling interval in seconds |
| `temperature_step` | float | No | 1.0 | Temperature adjustment step (1.0 or 0.5) |
| `include_sensors` | boolean | No | True | Create sensor entities for temperatures |
| `include_zones` | boolean | No | True | Create switch entities for zones |

#### 3.8.2 Config Flow Implementation

```python
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
import voluptuous as vol

from .const import DOMAIN, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL
from .client import AirTouch3Client

# Schema for initial setup
STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
})


class AirTouch3ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for AirTouch 3."""
    
    VERSION = 1
    
    def __init__(self):
        """Initialize config flow."""
        self._discovered_device: dict | None = None
    
    async def async_step_user(self, user_input=None):
        """
        Handle user-initiated config flow.
        
        This is shown when user clicks "+ Add Integration" and selects AirTouch 3.
        """
        errors = {}
        
        if user_input is not None:
            # Validate the connection
            client = AirTouch3Client(
                user_input[CONF_HOST],
                user_input.get(CONF_PORT, DEFAULT_PORT)
            )
            
            try:
                if await client.connect():
                    # Get device info for unique ID
                    state = await client.get_state()
                    await client.disconnect()
                    
                    if state:
                        device_id = state.device_id
                        
                        # Check if already configured
                        await self.async_set_unique_id(device_id)
                        self._abort_if_unique_id_configured()
                        
                        # Create the config entry
                        return self.async_create_entry(
                            title=state.system_name or f"AirTouch 3 ({user_input[CONF_HOST]})",
                            data={
                                CONF_HOST: user_input[CONF_HOST],
                                CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
                            },
                        )
                    else:
                        errors["base"] = "no_state"
                else:
                    errors["base"] = "cannot_connect"
                    
            except Exception:
                errors["base"] = "unknown"
            finally:
                await client.disconnect()
        
        # Show the form
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow handler."""
        return AirTouch3OptionsFlow(config_entry)


class AirTouch3OptionsFlow(config_entries.OptionsFlow):
    """Options flow for AirTouch 3 (Configure button)."""
    
    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize options flow."""
        self.config_entry = config_entry
    
    async def async_step_init(self, user_input=None):
        """
        Handle options flow.
        
        This is shown when user clicks "Configure" on existing integration.
        """
        if user_input is not None:
            # Save the options
            return self.async_create_entry(title="", data=user_input)
        
        # Get current options (or defaults)
        current_options = self.config_entry.options
        
        options_schema = vol.Schema({
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=current_options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            vol.Optional(
                "include_sensors",
                default=current_options.get("include_sensors", True),
            ): bool,
            vol.Optional(
                "include_zones",
                default=current_options.get("include_zones", True),
            ): bool,
        })
        
        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
```

#### 3.8.3 Reconfigure Flow (Change IP Address)

Users may need to change the IP if their device gets a new address. Add a reconfigure flow:

```python
class AirTouch3ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    # ... existing code ...
    
    async def async_step_reconfigure(self, user_input=None):
        """
        Handle reconfiguration (change IP address).
        
        Triggered from integration page "Reconfigure" option.
        """
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        
        if user_input is not None:
            # Validate new connection
            client = AirTouch3Client(
                user_input[CONF_HOST],
                user_input.get(CONF_PORT, DEFAULT_PORT)
            )
            
            try:
                if await client.connect():
                    state = await client.get_state()
                    await client.disconnect()
                    
                    if state and state.device_id == entry.unique_id:
                        # Same device, update the entry
                        return self.async_update_reload_and_abort(
                            entry,
                            data={
                                CONF_HOST: user_input[CONF_HOST],
                                CONF_PORT: user_input.get(CONF_PORT, DEFAULT_PORT),
                            },
                        )
                    elif state:
                        errors["base"] = "different_device"
                    else:
                        errors["base"] = "no_state"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            finally:
                await client.disconnect()
        
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST)): str,
                vol.Optional(CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)): int,
            }),
            errors=errors,
        )
```

#### 3.8.4 User Experience Flow

**Adding the Integration:**

```
User clicks "+ Add Integration"
         │
         ▼
Searches for "AirTouch 3"
         │
         ▼
┌─────────────────────────────────┐
│    Connect to AirTouch 3        │
│                                 │
│  Enter the IP address of your   │
│  AirTouch 3 device.             │
│                                 │
│  IP Address: [192.168.1.100  ]  │
│  Port:       [8899           ]  │
│                                 │
│         [Cancel]  [Submit]      │
└─────────────────────────────────┘
         │
         ▼ (on success)
┌─────────────────────────────────┐
│    Success!                     │
│                                 │
│  Found: "Home AC System"        │
│  Device ID: 12345678            │
│  AC Units: 1                    │
│  Zones: 6                       │
│                                 │
│              [Finish]           │
└─────────────────────────────────┘
```

**Configuring Existing Integration:**

```
User clicks "Configure" on integration card
         │
         ▼
┌─────────────────────────────────┐
│    AirTouch 3 Options           │
│                                 │
│  Poll Interval (seconds):       │
│  [30                         ]  │
│                                 │
│  ☑ Create temperature sensors   │
│  ☑ Create zone switches         │
│                                 │
│         [Cancel]  [Submit]      │
└─────────────────────────────────┘
```

**Changing IP Address (Reconfigure):**

```
User clicks "..." menu → "Reconfigure"
         │
         ▼
┌─────────────────────────────────┐
│    Reconfigure AirTouch 3       │
│                                 │
│  Update connection details:     │
│                                 │
│  IP Address: [192.168.1.150  ]  │
│  Port:       [8899           ]  │
│                                 │
│         [Cancel]  [Submit]      │
└─────────────────────────────────┘
```
```

### 3.9 `__init__.py` - Integration Setup

```python
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, CONF_INCLUDE_SENSORS, CONF_INCLUDE_ZONES
from .client import AirTouch3Client
from .coordinator import AirTouch3Coordinator

# Define which platforms to set up
PLATFORMS = [Platform.CLIMATE]  # Always include climate


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up AirTouch 3 from config entry.
    
    Called when:
    - Integration is first added
    - Home Assistant restarts
    - Integration is reloaded
    """
    hass.data.setdefault(DOMAIN, {})
    
    # Create client with connection details from config
    client = AirTouch3Client(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, 8899),
    )
    
    # Get options (with defaults)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    include_sensors = entry.options.get(CONF_INCLUDE_SENSORS, True)
    include_zones = entry.options.get(CONF_INCLUDE_ZONES, True)
    
    # Create coordinator
    coordinator = AirTouch3Coordinator(
        hass,
        client,
        name=f"AirTouch 3 ({entry.data[CONF_HOST]})",
        update_interval=timedelta(seconds=scan_interval),
    )
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()
    
    # Store coordinator for access by entities and unload
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # Build list of platforms to load
    platforms = [Platform.CLIMATE]  # Always load climate
    if include_zones:
        platforms.append(Platform.SWITCH)
    if include_sensors:
        platforms.append(Platform.SENSOR)
    
    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    
    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload config entry.
    
    Called when:
    - User removes the integration
    - Integration is being reloaded
    """
    # Determine which platforms are loaded
    platforms = [Platform.CLIMATE]
    if entry.options.get(CONF_INCLUDE_ZONES, True):
        platforms.append(Platform.SWITCH)
    if entry.options.get(CONF_INCLUDE_SENSORS, True):
        platforms.append(Platform.SENSOR)
    
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    
    if unload_ok:
        # Disconnect client
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    
    return unload_ok


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Handle options update.
    
    Called when user changes options via Configure button.
    Easiest approach is to reload the integration.
    """
    await hass.config_entries.async_reload(entry.entry_id)
```

#### Key Integration Lifecycle Events

| Event | Method Called | What to Do |
|-------|---------------|------------|
| Integration added | `async_setup_entry` | Create client, coordinator, load platforms |
| HA startup | `async_setup_entry` | Same as above |
| Options changed | `async_options_updated` | Reload integration |
| IP reconfigured | `async_setup_entry` (after reload) | Uses new config data |
| Integration removed | `async_unload_entry` | Disconnect, cleanup |
| HA shutdown | `async_unload_entry` | Disconnect, cleanup |
```

### 3.10 `manifest.json`

```json
{
  "domain": "airtouch3",
  "name": "AirTouch 3",
  "codeowners": ["@yourusername"],
  "config_flow": true,
  "documentation": "https://github.com/yourusername/ha-airtouch3",
  "integration_type": "hub",
  "iot_class": "local_polling",
  "requirements": [],
  "version": "1.0.0"
}
```

### 3.11 `strings.json`

This file defines all user-facing text. Home Assistant uses this for the UI.

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Connect to AirTouch 3",
        "description": "Enter the IP address of your AirTouch 3 device. You can find this in your router's connected devices list or in the AirTouch app under Settings.",
        "data": {
          "host": "IP Address",
          "port": "Port"
        },
        "data_description": {
          "host": "Local IP address (e.g., 192.168.1.100)",
          "port": "TCP port (default 8899, rarely needs changing)"
        }
      },
      "reconfigure": {
        "title": "Reconfigure AirTouch 3",
        "description": "Update the connection details for your AirTouch 3 device.",
        "data": {
          "host": "IP Address",
          "port": "Port"
        }
      }
    },
    "error": {
      "cannot_connect": "Failed to connect. Check the IP address and ensure the device is powered on.",
      "no_state": "Connected but received no data. The device may be busy - try again.",
      "different_device": "This IP belongs to a different AirTouch 3 device.",
      "unknown": "An unexpected error occurred. Check the logs for details."
    },
    "abort": {
      "already_configured": "This AirTouch 3 device is already configured.",
      "reconfigure_successful": "Connection updated successfully."
    }
  },
  "options": {
    "step": {
      "init": {
        "title": "AirTouch 3 Options",
        "description": "Configure how the integration behaves.",
        "data": {
          "scan_interval": "Poll interval (seconds)",
          "include_sensors": "Create temperature sensors",
          "include_zones": "Create zone switches"
        },
        "data_description": {
          "scan_interval": "How often to poll the device for updates (10-300 seconds)",
          "include_sensors": "Create sensor entities for AC and zone temperatures",
          "include_zones": "Create switch entities to control individual zones"
        }
      }
    }
  },
  "entity": {
    "climate": {
      "ac": {
        "name": "AC {ac_number}",
        "state_attributes": {
          "brand_id": {
            "name": "Brand ID"
          },
          "error_code": {
            "name": "Error Code"
          }
        }
      }
    },
    "switch": {
      "zone": {
        "name": "{zone_name}",
        "state_attributes": {
          "damper_percent": {
            "name": "Damper Opening"
          },
          "is_spill": {
            "name": "Spill Zone"
          }
        }
      }
    },
    "sensor": {
      "temperature": {
        "name": "{zone_name} Temperature"
      },
      "damper": {
        "name": "{zone_name} Damper"
      }
    }
  },
  "exceptions": {
    "cannot_connect": {
      "message": "Cannot connect to AirTouch 3 at {host}:{port}"
    },
    "command_failed": {
      "message": "Failed to send command to AirTouch 3"
    }
  }
}
```

### 3.12 `translations/en.json`

This is a copy of `strings.json` for English translations. For a single-language integration, you can symlink or duplicate the content. Additional languages would go in separate files (e.g., `translations/de.json` for German).

```json
// Same content as strings.json
```

### 3.13 Constants for Config (`const.py` additions)

Add these configuration-related constants:

```python
# Configuration keys
CONF_INCLUDE_SENSORS = "include_sensors"
CONF_INCLUDE_ZONES = "include_zones"

# Defaults
DEFAULT_PORT = 8899
DEFAULT_SCAN_INTERVAL = 30  # seconds
DEFAULT_INCLUDE_SENSORS = True
DEFAULT_INCLUDE_ZONES = True

# Validation limits
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 300
```
```

---

## 4. Key Implementation Details

### 4.1 Toggle Command Handling

**Critical**: Most commands (power, zone) are toggles, not absolute sets.

```python
async def turn_on_zone(self, zone_num: int) -> bool:
    """Turn zone on, handling toggle protocol."""
    current_state = self.coordinator.data.zones[zone_num]
    
    if current_state.is_on:
        # Already on, do nothing
        return True
    
    # Currently off, send toggle to turn on
    success = await self.client.zone_toggle(zone_num)
    if success:
        await self.coordinator.async_request_refresh()
    return success
```

### 4.2 Temperature Setting Loop

Since we can only increment/decrement:

```python
async def ac_set_temperature(self, ac_num: int, target: int) -> bool:
    """Set temperature by looping increments."""
    MAX_ATTEMPTS = 20  # Safety limit
    
    for _ in range(MAX_ATTEMPTS):
        state = await self.get_state()
        current = state.ac_units[ac_num].setpoint
        
        if current == target:
            return True
        elif current < target:
            await self._send_command(self._create_ac_temp_up(ac_num))
        else:
            await self._send_command(self._create_ac_temp_down(ac_num))
    
    return False  # Failed to reach target
```

### 4.3 Brand-Specific Mode Remapping

```python
def _encode_mode(self, mode: AcMode, brand: int) -> int:
    """Encode mode for command, applying brand remapping."""
    value = int(mode)
    
    if brand == BRAND_REMAP_11:
        # AUTO=0, HEAT=1→2, DRY=2→3, FAN=3→4, COOL=4→1
        remap = {0: 0, 1: 2, 2: 3, 3: 4, 4: 1}
        return remap.get(value, value)
    elif brand == BRAND_REMAP_15:
        # AUTO=0→5, HEAT=1→2, DRY=2→3, FAN=3→4, COOL=4→1
        remap = {0: 5, 1: 2, 2: 3, 3: 4, 4: 1}
        return remap.get(value, value)
    
    return value

def _decode_mode(self, value: int, brand: int) -> AcMode:
    """Decode mode from state message, reversing brand remapping."""
    if brand in (BRAND_REMAP_11, BRAND_REMAP_15):
        # Reverse mapping
        decode = {0: 0, 1: 4, 2: 1, 3: 2, 4: 3, 5: 0}
        value = decode.get(value, value)
    
    return AcMode(value) if value < 5 else AcMode.AUTO
```

### 4.4 Async TCP Connection Pattern

```python
import asyncio

class AirTouch3Client:
    def __init__(self, host: str, port: int = 8899):
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.buffer = MessageBuffer()
        self._lock = asyncio.Lock()  # Prevent concurrent commands
        
    async def connect(self) -> bool:
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=CONNECT_TIMEOUT
            )
            
            # Send init and get first state
            init_msg = self._create_command(CMD_INIT)
            return await self._send_command(init_msg) is not None
            
        except (asyncio.TimeoutError, OSError) as e:
            logger.error("Connection failed: %s", e)
            return False
            
    async def _send_command(self, command: bytes) -> SystemState | None:
        """Send command and receive state response."""
        async with self._lock:  # Serialize commands
            if not self.writer:
                return None
                
            self.writer.write(command)
            await self.writer.drain()
            
            # Read until we get a complete 492-byte state
            while True:
                try:
                    data = await asyncio.wait_for(
                        self.reader.read(1024),
                        timeout=READ_TIMEOUT
                    )
                    if not data:
                        return None  # Connection closed
                        
                    messages = self.buffer.add_data(data)
                    for msg in messages:
                        if len(msg) == STATE_MSG_SIZE:
                            return self._parse_state(msg)
                            
                except asyncio.TimeoutError:
                    continue  # Timeout is normal, keep trying
```

### 4.5 Entity Unique IDs and Device Registry

```python
# Use device_id from state message (bytes 483-490) as base

class AirTouch3Climate:
    @property
    def unique_id(self) -> str:
        device_id = self.coordinator.data.device_id
        return f"{device_id}_ac_{self.ac_number}"
    
    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.data.device_id)},
            name=self.coordinator.data.system_name or "AirTouch 3",
            manufacturer="Polyaire",
            model="AirTouch 3",
        )
```

---

## 5. Error Handling

### 5.1 Connection Errors

| Error | Handling |
|-------|----------|
| Connection timeout | Retry with backoff, mark entities unavailable |
| Connection refused | Device offline, mark unavailable |
| Connection lost mid-session | Reconnect on next update |
| Read timeout | Normal during idle, continue loop |

### 5.2 Protocol Errors

| Error | Handling |
|-------|----------|
| Unexpected message size | Log warning, skip message |
| Parse error | Log error, return None from parse |
| Command no response | Retry once, then fail |
| Checksum mismatch | Log warning, skip message |

### 5.3 Coordinator Error Handling

```python
async def _async_update_data(self) -> SystemState:
    try:
        if not self.client.connected:
            if not await self.client.connect():
                raise UpdateFailed("Cannot connect to device")
        
        state = await self.client.get_state()
        if state is None:
            raise UpdateFailed("No state received")
            
        return state
        
    except (OSError, asyncio.TimeoutError) as err:
        raise UpdateFailed(f"Communication error: {err}") from err
```

---

## 6. Testing Strategy

### 6.1 Unit Tests

- `test_client.py`: Test message creation, checksum, parsing
- `test_models.py`: Test data class construction
- `test_coordinator.py`: Test state update handling (mock client)
- `test_climate.py`: Test mode mapping, temperature logic
- `test_config_flow.py`: Test config flow steps

### 6.2 Mock Device

Create a mock TCP server that responds with sample 492-byte state messages for integration testing without real hardware.

```python
class MockAirTouch3Server:
    """Mock server for testing."""
    
    def __init__(self):
        self.state = self._create_default_state()
        
    async def handle_client(self, reader, writer):
        while True:
            data = await reader.read(13)
            if not data:
                break
            # Process command and send state
            writer.write(self.state)
            await writer.drain()
```

### 6.3 Integration Tests

Test against real device:
- Connection establishment
- State parsing accuracy
- Command execution
- Mode changes
- Temperature changes
- Zone control

---

## 7. Future Enhancements

### 7.1 Phase 2 Features
- Zone damper control as Number entities
- AC timer scheduling
- Program schedule configuration
- Favorite scene activation
- Zone naming from HA

### 7.2 Phase 3 Features
- Device discovery (scan network for port 8899)
- Energy monitoring (from running hours)
- Diagnostics integration
- Service calls for advanced functions

---

## 8. HACS Distribution Requirements

### 8.1 Repository Structure

For HACS distribution, your GitHub repository should look like this:

```
ha-airtouch3/                      # Repository root
├── README.md                      # User documentation
├── hacs.json                      # HACS metadata
├── custom_components/
│   └── airtouch3/
│       ├── __init__.py
│       ├── manifest.json
│       ├── config_flow.py
│       ├── coordinator.py
│       ├── climate.py
│       ├── switch.py
│       ├── sensor.py
│       ├── client.py
│       ├── models.py
│       ├── const.py
│       ├── strings.json
│       └── translations/
│           └── en.json
└── .github/
    └── workflows/
        └── validate.yml           # Optional: HACS validation
```

### 8.2 `hacs.json`

Required file in repository root:

```json
{
  "name": "AirTouch 3",
  "render_readme": true,
  "homeassistant": "2024.1.0"
}
```

| Field | Description |
|-------|-------------|
| `name` | Display name in HACS |
| `render_readme` | Show README.md in HACS |
| `homeassistant` | Minimum HA version required |

### 8.3 `manifest.json` Requirements

HACS validates this file. Required fields:

```json
{
  "domain": "airtouch3",
  "name": "AirTouch 3",
  "codeowners": ["@yourgithubusername"],
  "config_flow": true,
  "documentation": "https://github.com/yourusername/ha-airtouch3",
  "integration_type": "hub",
  "iot_class": "local_polling",
  "issue_tracker": "https://github.com/yourusername/ha-airtouch3/issues",
  "requirements": [],
  "version": "1.0.0"
}
```

| Field | Value | Why |
|-------|-------|-----|
| `domain` | `airtouch3` | Unique identifier, must match folder name |
| `config_flow` | `true` | We have a UI config flow |
| `integration_type` | `hub` | Device that exposes multiple entities |
| `iot_class` | `local_polling` | Local network, we poll for updates |
| `requirements` | `[]` | No PyPI dependencies (pure Python) |
| `version` | Semver | Required for HACS |

### 8.4 README.md for Users

Your README should include:

```markdown
# AirTouch 3 for Home Assistant

Control your Polyaire AirTouch 3 air conditioning system from Home Assistant.

## Features
- Climate entities for each AC unit (temperature, mode, fan speed)
- Switch entities for zone on/off control
- Temperature sensors for rooms and wireless sensors

## Installation

### HACS (Recommended)
1. Open HACS in Home Assistant
2. Click "Integrations"
3. Click the three dots menu → "Custom repositories"
4. Add `https://github.com/yourusername/ha-airtouch3` as an Integration
5. Click "Download"
6. Restart Home Assistant

### Manual
1. Download the `custom_components/airtouch3` folder
2. Copy to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration
1. Go to Settings → Devices & Services
2. Click "+ Add Integration"
3. Search for "AirTouch 3"
4. Enter your device's IP address

## Options
After adding, click "Configure" to adjust:
- **Poll interval**: How often to check device status (default: 30s)
- **Include sensors**: Create temperature sensor entities
- **Include zones**: Create zone switch entities

## Finding Your Device IP
- Check your router's connected devices list
- Or use the AirTouch app: Settings → Network

## Troubleshooting
- **Can't connect**: Ensure device is on same network as HA
- **No entities**: Check HA logs for errors
- **Stale data**: Try reducing poll interval

## Supported Devices
- AirTouch 3 (tested)
- May work with similar Polyaire systems

## Credits
Protocol reverse-engineered from AirTouch 3 Android app.
```

### 8.5 Version Numbering

Use semantic versioning in `manifest.json`:
- `1.0.0` - Initial release
- `1.0.1` - Bug fixes
- `1.1.0` - New features (backward compatible)
- `2.0.0` - Breaking changes

Update the version when creating GitHub releases. HACS uses GitHub releases for updates.

### 8.6 GitHub Releases

To publish updates:
1. Update `version` in `manifest.json`
2. Commit and push
3. Create a GitHub Release with a tag matching the version (e.g., `v1.0.0`)
4. HACS will detect the new release

---

## 9. Development Checklist

### Phase 1: Core Functionality
- [ ] `const.py` - All protocol constants
- [ ] `models.py` - Data classes
- [ ] `client.py` - TCP client with basic commands
- [ ] `client.py` - State parsing (all byte offsets)
- [ ] `coordinator.py` - Update coordinator
- [ ] `climate.py` - Basic climate entity
- [ ] `switch.py` - Zone switches
- [ ] `config_flow.py` - Manual IP entry + options flow
- [ ] `__init__.py` - Integration setup
- [ ] `manifest.json` and `strings.json`
- [ ] Test against real device

### Phase 2: Polish
- [ ] `sensor.py` - Temperature sensors
- [ ] Error handling improvements
- [ ] Reconnection logic
- [ ] Brand-specific testing
- [ ] Options flow (scan interval, entity toggles)
- [ ] Reconfigure flow (change IP)

### Phase 3: Distribution
- [ ] Create GitHub repository
- [ ] Add README.md with installation instructions
- [ ] Add hacs.json
- [ ] Test HACS installation
- [ ] Create first GitHub release
- [ ] Submit to HACS default repositories (optional)

---

## 10. Reference: State Message Quick Reference

| Offset | Length | Content |
|--------|--------|---------|
| 104-231 | 128 | Zone names (16 × 8 chars) |
| 232-247 | 16 | Zone on/off, spill, program |
| 248-263 | 16 | Zone damper % |
| 296-311 | 16 | Zone setpoint & sensor source |
| 352 | 1 | Total zone count |
| 353 | 1 | Dual-ducted flag (bit 0), AC1 group count (bits 1-7) |
| 383-398 | 16 | System name |
| 399-414 | 16 | AC names (2 × 8 chars) |
| 423-424 | 2 | AC power (bit 0), error (bit 1), program (bits 2-4) |
| 425-426 | 2 | AC brand IDs |
| 427-428 | 2 | AC mode (bits 0-6) |
| 429-430 | 2 | AC fan: supported (bits 4-7), current (bits 0-3) |
| 431-432 | 2 | AC setpoint temp (bits 0-6) |
| 433-434 | 2 | AC room temp |
| 435-438 | 4 | AC error codes (2 × 2 bytes) |
| 439-440 | 2 | AC unit/gateway IDs |
| 443-446 | 4 | Touchpad zone (443, 444), temp (445 bits 1-7, 446 bits 1-7) |
| 451-482 | 32 | Wireless sensors (available, battery, temp) |
| 483-490 | 8 | Device ID (low nibbles) |

---

## 11. Appendix: Sample State Parsing Code

Reference implementation for parsing (from PROTOCOL_DOCUMENTATION.md):

```python
def parse_state(data: bytes) -> SystemState:
    """Parse 492-byte state message."""
    
    # Device ID (bytes 483-490, low nibbles concatenated)
    device_id = "".join(str(data[i] & 0x0F) for i in range(483, 491))
    
    # System name (bytes 383-398, ASCII, strip spaces)
    system_name = bytes(data[383:399]).decode('ascii', errors='ignore').strip()
    
    # Zone count (byte 352)
    zone_count = data[352]
    
    # Dual ducted (byte 353, bit 0)
    is_dual_ducted = bool(data[353] & 0x01)
    
    # Parse AC units
    ac_units = []
    for ac_num in range(2):
        # Power/error (byte 423 + ac_num)
        status = data[423 + ac_num]
        power_on = bool(status & 0x01)
        has_error = bool(status & 0x02)
        
        # Brand (byte 425 + ac_num)
        brand_id = data[425 + ac_num]
        
        # Mode (byte 427 + ac_num, bits 0-6)
        mode_raw = data[427 + ac_num] & 0x7F
        mode = _decode_mode(mode_raw, brand_id)
        
        # Fan (byte 429 + ac_num)
        fan_byte = data[429 + ac_num]
        supported_fans = (fan_byte >> 4) & 0x0F
        fan_speed = fan_byte & 0x0F
        
        # Setpoint (byte 431 + ac_num, bits 0-6)
        setpoint = data[431 + ac_num] & 0x7F
        
        # Room temp (byte 433 + ac_num)
        room_temp = data[433 + ac_num]
        if room_temp > 127:
            room_temp = room_temp - 256  # Handle negative
        
        # Name (bytes 399-406 for AC1, 407-414 for AC2)
        name_start = 399 + (ac_num * 8)
        name = bytes(data[name_start:name_start + 8]).decode('ascii', errors='ignore').strip()
        
        ac_units.append(AcState(
            ac_number=ac_num,
            name=name,
            power_on=power_on,
            mode=mode,
            fan_speed=fan_speed,
            setpoint=setpoint,
            room_temp=room_temp,
            brand_id=brand_id,
            has_error=has_error,
            error_code=0,  # Parse from 435-438 if needed
            supported_fan_speeds=_decode_supported_fans(supported_fans),
            control_mode=_get_control_mode(data[439 + ac_num], brand_id),
        ))
    
    # Parse zones
    zones = []
    for zone_num in range(zone_count):
        # Name (8 bytes starting at 104 + zone_num * 8)
        name_start = 104 + (zone_num * 8)
        name = bytes(data[name_start:name_start + 8]).decode('ascii', errors='ignore').strip()
        
        # Status (byte 232 + zone_num)
        zone_data = data[232 + zone_num]
        is_on = bool(zone_data & 0x01)
        is_spill = bool(zone_data & 0x02)
        program = (zone_data >> 2) & 0x07
        
        # Damper (byte 248 + zone_num, bits 0-6 × 5)
        damper = (data[248 + zone_num] & 0x7F) * 5
        
        # Feedback (byte 296 + zone_num)
        feedback = data[296 + zone_num]
        sensor_source = (feedback >> 5) & 0x07
        zone_setpoint = (feedback & 0x1F) + 1 if sensor_source > 0 else None
        
        zones.append(ZoneState(
            zone_number=zone_num,
            name=name,
            is_on=is_on,
            is_spill=is_spill,
            damper_percent=damper,
            active_program=program,
            setpoint=zone_setpoint,
            sensor_source=sensor_source,
        ))
    
    return SystemState(
        raw_data=data,
        device_id=device_id,
        system_name=system_name,
        zone_count=zone_count,
        is_dual_ducted=is_dual_ducted,
        ac_units=ac_units,
        zones=zones,
        sensors=[],  # Parse bytes 451-482 if needed
        touchpads=[],  # Parse bytes 443-446 if needed
    )
```

---

*Document Version: 1.0*
*Created: December 2024*
*Based on: PROTOCOL_DOCUMENTATION.md and Home Assistant Developer Documentation*
