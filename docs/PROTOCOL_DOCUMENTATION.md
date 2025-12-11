# AirTouch 3 Protocol Documentation

## Overview

This document describes the reverse-engineered TCP protocol used by the Polyaire AirTouch 3 system for local network communication. The protocol uses raw TCP sockets with binary message formats to control air conditioning units and zones.

---

## Connection Information

| Parameter | Value |
|-----------|-------|
| Protocol | Raw TCP Socket |
| Port | `8899` |
| IP Address | Device's local network IP |
| Encryption | None (plain TCP) |
| Message Format | Binary (fixed-length byte arrays) |

---

## Message Structure

### Command Messages (13 bytes)

All commands sent TO the device follow this structure:

```
┌─────┬─────┬─────┬─────┬─────┬─────┬─────────────┬─────────┐
│  0  │  1  │  2  │  3  │  4  │  5  │   6 - 11    │   12    │
├─────┼─────┼─────┼─────┼─────┼─────┼─────────────┼─────────┤
│0x55 │ CMD │0x0C │ P1  │ P2  │ P3  │ 0x00 (×6)   │ CHKSUM  │
└─────┴─────┴─────┴─────┴─────┴─────┴─────────────┴─────────┘
```

**Field Descriptions:**
- **Byte 0**: Magic number/header (always `0x55` / 85 decimal)
- **Byte 1**: Command type identifier
- **Byte 2**: Message length (always `0x0C` / 12 decimal)
- **Byte 3**: Parameter 1 (context-dependent)
- **Byte 4**: Parameter 2 (context-dependent)
- **Byte 5**: Parameter 3 (context-dependent)
- **Bytes 6-11**: Reserved (always `0x00`)
- **Byte 12**: Checksum (sum of bytes 0-11, masked to 8 bits)

**Checksum Calculation:**
```python
checksum = sum(message[0:12]) & 0xFF
```
Example (init command):
```python
init = [0x55, 0x01, 0x0C] + [0x00] * 9  # 12 bytes
checksum = sum(init) & 0xFF  # 0x62
init.append(checksum)
```

**Bit numbering note:** When this document refers to “bit X”, use masks on the raw byte (`byte & (1 << X)`) rather than relying on string index order. The Android app turns bytes into binary strings with bit 7 on the left and bit 0 on the right, which is easy to misread. Always mask bits directly to avoid inversion mistakes.

### State Messages (492 bytes)

The device sends 492-byte status messages containing complete system state. These are sent:
- After connection initialization
- After processing any command
- Periodically (as a keepalive/state sync)

---

## Command Reference

### 1. Initialization

**Purpose:** Must be sent immediately after TCP connection is established.

**Message Format:**
```
[0x55, 0x01, 0x0C, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x62]
```

**Breakdown:**
- Byte 1: `0x01` - Init command
- Bytes 3-11: All zeros
- Byte 12: `0x62` (checksum)

**Expected Response:** 492-byte state message

---

### 2. AC Power Control

**Purpose:** Toggle AC unit on/off

**Important:** This command toggles the current state. If multiple controllers are active, read the current state first and only send when you know the target state.

**Message Format:**
```
Byte 0:  0x55
Byte 1:  0x86  (or -122 as signed byte)
Byte 2:  0x0C
Byte 3:  AC_NUM (0 for AC1, 1 for AC2)
Byte 4:  0x80  (or -128 as signed byte)
Byte 5-11: 0x00
Byte 12: Checksum
```

**Example (AC1 toggle):**
```
[0x55, 0x86, 0x0C, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, <checksum>]
```

---

### 3. Temperature Adjustment

**Purpose:** Increment or decrement target temperature by 1°C

**Important:** There is no direct "set to X" command. To reach a target, loop sending `TEMP_CMD` up/down until the reported setpoint (bytes 431/432) matches your goal, and respect min/max limits reported by the unit.

**Message Format:**
```
Byte 0:  0x55
Byte 1:  0x86
Byte 2:  0x0C
Byte 3:  AC_NUM (0 for AC1, 1 for AC2)
Byte 4:  TEMP_CMD
         0xA3 (163 or -93 signed) = Increase by 1°C
         0x93 (147 or -109 signed) = Decrease by 1°C
Byte 5-11: 0x00
Byte 12: Checksum
```

**Example (Increase AC1 temp):**
```
[0x55, 0x86, 0x0C, 0x00, 0xA3, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, <checksum>]
```

**Note:** Temperature cannot be set directly to a specific value, only incremented/decremented.

---

### 4. AC Mode Selection

**Purpose:** Set operating mode (Auto, Heat, Cool, Dry, Fan)

**Message Format:**
```
Byte 0:  0x55
Byte 1:  0x86
Byte 2:  0x0C
Byte 3:  AC_NUM
Byte 4:  MODE_CMD (brand-specific, see note below)
Byte 5:  MODE_VALUE
Byte 6-11: 0x00
Byte 12: Checksum
```

**Mode Values (Byte 5):**
- `0` = Auto
- `1` = Heat
- `2` = Dry
- `3` = Fan
- `4` = Cool

**Important:** Byte 4 is always `0x81` (129). Mode remapping affects byte 5 only:
- Brand 11: Modes are remapped (0→0, 1→2, 2→3, 3→4, 4→1)
- Brand 15: Modes are remapped (0→5, 1→2, 2→3, 3→4, 4→1)
- Other brands: Use mode value directly in byte 5

Apply the same remapping when **decoding** bytes 427/428 from the state message so UI state matches what was sent.

**Example (Set AC1 to Cool mode, non-remapped brand):**
```
[0x55, 0x86, 0x0C, 0x00, 0x81, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, <checksum>]
```

---

### 5. Fan Speed Control

**Purpose:** Set fan speed

**Message Format:**
```
Byte 0:  0x55
Byte 1:  0x86
Byte 2:  0x0C
Byte 3:  AC_NUM
Byte 4:  0x82 (or -126 as signed)
Byte 5:  FAN_SPEED (brand-specific value)
Byte 6-11: 0x00
Byte 12: Checksum
```

**Fan Speed Modes:**
- Auto
- Low
- Medium
- High
- Quiet
- Powerful

**Note:** The actual byte value for each fan speed is brand-dependent and must be calculated using the AC brand ID and supported fan speeds from the state message.

**Tip:** Read the supported fan bitmap (high nibble of bytes 429/430) before sending; unsupported values are ignored by some brands.

---

### 6. Zone Control

**Purpose:** Toggle individual zone on/off

**Important:** This is also a toggle. Read the latest 492-byte state to determine current zone status before changing it.

**Message Format:**
```
Byte 0:  0x55
Byte 1:  0x81  (129 unsigned, -127 signed)
Byte 2:  0x0C
Byte 3:  ZONE_NUM (0-based zone index)
Byte 4:  0x80
Byte 5:  0x00  (Zone power toggle)
Byte 6-11: 0x00
Byte 12: Checksum
```

**Example (Toggle Zone 0 power):**
```
[0x55, 0x81, 0x0C, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, <checksum>]
```

---

### 7. Zone Control Mode Toggle

**Purpose:** Toggle zone between temperature setpoint mode and damper percentage mode

Only applicable to zones with temperature sensors. When in temperature mode, the zone maintains a target temperature. When in percentage mode, the zone uses a fixed damper opening.

**Message Format:**
```
Byte 0:  0x55
Byte 1:  0x81  (129 unsigned, -127 signed)
Byte 2:  0x0C
Byte 3:  ZONE_NUM (0-based zone index)
Byte 4:  0x80
Byte 5:  0x01  (Mode toggle - distinguishes from power toggle)
Byte 6-11: 0x00
Byte 12: Checksum
```

**Example (Toggle Zone 0 control mode):**
```
[0x55, 0x81, 0x0C, 0x00, 0x80, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, <checksum>]
```

**Note:** The current mode is indicated by bit 7 (0x80) of the damper byte (bytes 248-263). When set, the zone is in temperature control mode.

---

### 8. Zone Value Adjustment

**Purpose:** Adjust zone value (temperature setpoint or damper percentage, depending on current mode)

**Message Format:**
```
Byte 0:  0x55
Byte 1:  0x81  (129 unsigned, -127 signed)
Byte 2:  0x0C
Byte 3:  ZONE_NUM
Byte 4:  DIRECTION
         0x02 = Increase (UP)
         0x01 = Decrease (DOWN)
Byte 5:  0x01
Byte 6-11: 0x00
Byte 12: Checksum
```

In **temperature mode**: Adjusts setpoint by 1°C per command
In **percentage mode**: Adjusts damper opening by 5% per command

---

## State Message Structure (492 bytes)

The device continuously sends 492-byte messages containing complete system state. The Android app converts bytes to binary strings for parsing, but when implementing you should mask the raw bytes (`byte & (1 << X)`) to avoid bit-order confusion (the strings are rendered with bit 7 on the left and bit 0 on the right).

### Byte Map Overview

| Byte Range | Content |
|------------|---------|
| 0-1 | Header/message type |
| 2-7 | Date/Time |
| 8-103 | Program schedules (96 bytes) |
| 104-231 | Zone names (128 bytes, 16 zones × 8 chars) |
| 232-247 | Zone data (16 bytes) |
| 248-263 | Zone open/damper status (16 bytes) |
| 264-279 | Group data (16 bytes) |
| 280-295 | Zone balance (16 bytes) |
| 296-311 | Zone feedback/sensor assignment (16 bytes) |
| 312-343 | Favorite names (4 × 8 chars) |
| 344-351 | Favorite zone assignments |
| 352-359 | System parameters |
| 360 | Turbo/Spill flags |
| 361-382 | Service contact info |
| 383-398 | System name (16 chars) |
| 399-414 | AC names (2 × 8 chars) |
| 415-422 | AC timer data |
| 423-424 | AC power/error/program status |
| 425-426 | AC brand IDs |
| 427-428 | AC mode/fan data |
| 429-430 | AC fan speed data |
| 431-432 | AC setpoint temperatures |
| 433-434 | AC room temperatures |
| 435-438 | AC error codes |
| 439-440 | AC unit IDs |
| 441-442 | AC thermostat assignments |
| 443-446 | Touchpad data |
| 447-450 | AC running hours |
| 451-482 | Wireless sensors (32 slots) |
| 483-490 | AirTouch device ID (8 bytes) |
| 491 | Reserved/padding |

---

### Header / Message Type (Bytes 0-1)

- Present in every 492-byte frame. The app does not branch on these bytes; treat them as reserved framing fields and keep them intact for sanity checks and potential future validation.

---

### Date/Time (Bytes 2-7)

| Byte | Content |
|------|---------|
| 2-3 | Year (combined binary → decimal, e.g., "25" for 2025) |
| 4 | Month (0-11, add 1 for display) |
| 5 | Day (0-30, add 1 for display) |
| 6 | Hour (0-23) |
| 7 | Minute (0-59, add 1 for display) |

---

### Program Schedules (Bytes 8-103)

96 bytes total = 48 schedule slots × 2 bytes each.
- Program 1: Bytes 8-31 (24 bytes = 12 indices = 4 MF, 4 SAT, 4 SUN; each index is hour then minute)
- Program 2: Bytes 32-55
- Program 3: Bytes 56-79
- Program 4: Bytes 80-103

Each slot uses two bytes: hour, then minute. Indexing matches the `setProgramMessage()` formula in the Program Configuration section below. A cleared slot uses the “clear” command (byte 4 = 0x81) rather than magic hour/minute values.

---

### Zone Names (Bytes 104-231)

128 bytes for up to 16 zones, 8 ASCII characters per zone:
- Zone 0 name: Bytes 104-111
- Zone 1 name: Bytes 112-119
- Zone 2 name: Bytes 120-127
- ... and so on
- Zone 15 name: Bytes 224-231

Each byte is a binary-encoded ASCII character.

---

### Zone Data (Bytes 232-247)

16 bytes, one per zone. Each byte contains:

| Bit | Content |
|-----|---------|
| 7 | **Zone ON/OFF status** (`byte & 0x80`) - Use this bit! |
| 6 | Spill status (`byte & 0x40`) |
| 5-3 | Program number (bits 5-3, mask `(byte >> 2) & 0x07`) |
| 2-0 | Reserved/unused |

**Important:** The Android app uses **bit 7** (MSB) for zone ON/OFF determination. The app converts each byte to a binary string using `toFullBinaryString()` which produces MSB-first strings, then uses `substring(0,1)` to check the first character (bit 7). See WifiCommService.java lines 1178-1183.

**Note:** Program values > 4 should be subtracted by 4.

---

### Zone Open/Damper Status (Bytes 248-263)

16 bytes, one per zone. Each byte contains:

| Bit | Content |
|-----|---------|
| 7 | Temperature control mode (1=temperature, 0=percentage) |
| 6-0 | Damper opening value (multiply by 5 for percentage) |

- Parse bits 0-6 as `value = byte & 0x7F`
- Multiply by 5 to get percentage (0-100%)
- Bit 7 indicates whether the zone is in temperature setpoint mode (when a sensor is assigned)

**Note:** Damper position indicates the airflow percentage, NOT the zone ON/OFF state. Use bit 7 of Zone Data (bytes 232-247) for ON/OFF. A zone that is OFF may retain its previous damper position.

---

### Group Data (Bytes 264-279)

16 bytes mapping zones to AC units. Used for dual-ducted systems to determine which AC controls each zone.

Bits 0-3 (`byte & 0x0F`): Reference index into Zone Data array.

---

### Zone Balance (Bytes 280-295)

16 bytes for zone balance/airflow settings.

---

### Zone Feedback/Sensor Assignment (Bytes 296-311)

16 bytes, one per zone. Each byte contains:

| Bits | Content |
|------|---------|
| 5-7 | Temperature sensor source (`(byte >> 5) & 0x07`) |
| 0-4 | Zone setpoint temperature - 1 (`byte & 0x1F`, then `+1` for actual temp) |

**Sensor source values (mask `(byte >> 5) & 0x07`):**
- `0` = No temperature display
- `1` = Use sensor 1 (touchpad takes priority if assigned)
- `2` = Use sensor 2
- `3` = Use sensor 1 with sensor 2 fallback
- `4` = Use average of sensors

**Zone setpoint parsing:**
```python
feedback_byte = state[296 + zone_num]
sensor_source = (feedback_byte >> 5) & 0x07
zone_setpoint = (feedback_byte & 0x1F) + 1
```

---

### Favorite Names (Bytes 312-343)

4 favorites × 8 ASCII characters each:
- Favorite 1: Bytes 312-319
- Favorite 2: Bytes 320-327
- Favorite 3: Bytes 328-335
- Favorite 4: Bytes 336-343

---

### Favorite Zone Assignments (Bytes 344-351)

8 bytes encoding which zones are assigned to each favorite:
- Bytes 344-345: Favorite 1 (bits represent zones 0-7 and 8-15)
- Bytes 346-347: Favorite 2
- Bytes 348-349: Favorite 3
- Bytes 350-351: Favorite 4

---

### System Parameters (Bytes 352-359)

| Byte | Content |
|------|---------|
| 352 | Total zone/group count (full byte as decimal) |
| 353 bit 0 | Dual-ducted flag (1 = dual ducted) |
| 353 bits 1-7 | AC1 group count |
| 354 | (reserved/unknown – not referenced by the app) |
| 355 bits 1-7 | AC1 turbo zone number (bit 0 unused/unknown) |
| 356 bits 1-7 | AC2 turbo zone number (bit 0 unused/unknown) |
| 357 | Service reminder day |
| 358-359 | (reserved/unknown) |

To extract counts from bits 1-7, mask with `0xFE` and shift right one (e.g., `ac1_group_count = (byte_353 & 0xFE) >> 1`).

---

### Turbo and Spill Flags (Byte 360)

| Bit | Content |
|-----|---------|
| 2 | AC1 turbo active (`byte & 0x04`) |
| 3 | AC2 turbo active (`byte & 0x08`) |
| 4 | AC1 cooling/heating mode (`byte & 0x10`) |
| 5 | AC2 cooling/heating mode (`byte & 0x20`) |
| 6 | AC1 spill active (`byte & 0x40`) |
| 7 | AC2 spill active (`byte & 0x80`) |

---

### System Name (Bytes 383-398)

16 ASCII characters for system name. Trailing spaces (0x20) should be trimmed.

---

### AC Names (Bytes 399-414)

- AC1 name: Bytes 399-406 (8 ASCII characters)
- AC2 name: Bytes 407-414 (8 ASCII characters)

---

### AC Timer Data (Bytes 415-422)

| Byte | Bit | Content |
|------|-----|---------|
| 415 | 0 | AC1 timer enabled (`byte & 0x01`) |
| 417 | 0 | AC1 timer active (`byte & 0x01`) |
| 419 | 0 | AC2 timer enabled (`byte & 0x01`) |
| 421 | 0 | AC2 timer active (`byte & 0x01`) |

---

### AC Power/Error/Program Status (Bytes 423-424)

**Byte 423 (AC1):**
| Bit | Content |
|-----|---------|
| 7 | Power status (`byte & 0x80`, 1 = ON) |
| 1 | Error flag (`byte & 0x02`, 1 = error present) |
| 2-4 | Active program number (`(byte >> 2) & 0x07`; 0 = none, 1-4 = active) |

**Byte 424 (AC2):** Same structure as byte 423.

**IMPORTANT - Bit Numbering Trap:** The Android app converts bytes to binary strings using `toFullBinaryString()` which places bit 7 at string position 0 (MSB first). When the app checks `substring(0, 1)`, it's actually checking **bit 7**, not bit 0. The power status is in **bit 7** (mask `0x80`), NOT bit 0. This same pattern applies throughout the app's parsing code.

---

### AC Brand IDs (Bytes 425-426)

- Byte 425: AC1 brand ID (full byte as decimal)
- Byte 426: AC2 brand ID (full byte as decimal)

Known brands requiring special handling:
- Brand 2: Special fan speed adjustment
- Brand 11: Mode remapping, error code filtering (109-116 ignored)
- Brand 15: Mode remapping, Auto fan = value 4

---

### AC Mode and Fan Data (Bytes 427-430)

**Byte 427 (AC1 mode):**
- Bits 0-6: Mode value (`byte & 0x7F`, values 0-4 used)

**Byte 428 (AC2 mode):**
- Bits 0-6: Mode value (`byte & 0x7F`, values 0-4 used)

**Mode values (standard brands):**
| Value | Mode |
|-------|------|
| 0 | Auto |
| 1 | Heat |
| 2 | Dry |
| 3 | Fan |
| 4 | Cool |

**Mode values (Brand 11/15 - decoded differently):**
| Value | Mode |
|-------|------|
| 0 | Auto |
| 1 | Cool |
| 2 | Heat |
| 3 | Dry |
| 4 | Fan |

**Byte 429 (AC1 fan):**
- High nibble (bits 4-7): Supported fan speed bitmap (mask with `0xF0`, then shift right 4)
- Low nibble (bits 0-3): Current fan speed value (mask with `0x0F`)

**Byte 430 (AC2 fan):** Same structure as byte 429

**Supported Fan Speed Bitmap:**
| Value | Supported Modes |
|-------|-----------------|
| 2 | Low, High |
| 3 | Low, Medium, High |
| 4+ | Full (Quiet, Low, Med, High, Powerful) |

**Fan Speed Values (from state message):**
| Value | Mode |
|-------|------|
| 0 | Auto |
| 1 | Quiet (or Low if limited) |
| 2 | Low (or Medium if limited) |
| 3 | Medium (or High if limited) |
| 4 | High (or Powerful if full) |
| 5+ | Auto |

**Fan Speed Decoding Logic:**
```python
def decode_fan_speed(fan_value, brand, supported_speed):
    """Decode fan speed from state message."""
    # Brand 15 special case: value 4 = Auto
    if brand == 15 and fan_value == 4:
        return "Auto"

    # Value 0 or 5+ = Auto
    if fan_value == 0 or fan_value >= 5:
        return "Auto"

    fan_modes = ["Quiet", "Low", "Medium", "High", "Powerful"]

    # Brand 2 with supported=4: values are offset by 1
    if brand == 2 and supported_speed == 4:
        return fan_modes[fan_value - 1]

    return fan_modes[fan_value]
```

**Fan Speed Encoding Logic (for commands):**
```python
def encode_fan_speed(mode_name, brand, supported_speed):
    """Encode fan speed for command message."""
    if mode_name == "Auto":
        return 4 if brand == 15 else 0

    mode_values = {"Low": 1, "Medium": 2, "High": 3, "Powerful": 4}
    value = mode_values.get(mode_name, 0)

    # Brand 2 with supported=4: add 1 to value
    if brand == 2 and supported_speed == 4:
        return value + 1

    return value
```

---

### AC Setpoint Temperatures (Bytes 431-432)

- Byte 431 bits 0-6: AC1 setpoint temperature (°C, `byte & 0x7F`)
- Byte 432 bits 0-6: AC2 setpoint temperature (°C, `byte & 0x7F`)

---

### AC Room Temperatures (Bytes 433-434)

- Byte 433: AC1 room temperature (full byte as decimal)
- Byte 434: AC2 room temperature (full byte as decimal)

**Note:** Values > 127 indicate negative temperatures: `temp = value - 256`

---

### AC Error Codes (Bytes 435-438)

- Bytes 435-436: AC1 error code (low byte + high byte × 256)
- Bytes 437-438: AC2 error code (low byte + high byte × 256)

**Note:** For Brand 11, error codes 109-116 are filtered (set to 0).

---

### AC Unit IDs (Bytes 439-440)

- Byte 439: AC1 unit ID
- Byte 440: AC2 unit ID

**Control Mode Determination:**
| AC ID | Brand | Control Mode |
|-------|-------|--------------|
| 0 | 0 | Not Available |
| 0 | ≠0 | Basic Control |
| ≠0 | any | Full Control |

---

### AC Thermostat Assignments (Bytes 441-442)

- Byte 441: AC1 thermostat zone assignment
- Byte 442: AC2 thermostat zone assignment

---

### Touchpad Data (Bytes 443-446)

- Byte 443: Touchpad 1 assigned group (1-based, subtract 1 for zone index)
- Byte 444: Touchpad 2 assigned group
- Byte 445 bits 0-6: Touchpad 1 temperature reading (mask with `0x7F`)
- Byte 446 bits 0-6: Touchpad 2 temperature reading (mask with `0x7F`)

**Parsing:**
```python
touchpad1_zone = state[443] - 1  # 0-indexed, -1 if unassigned
touchpad2_zone = state[444] - 1
touchpad1_temp = state[445] & 0x7F  # Temperature in Celsius
touchpad2_temp = state[446] & 0x7F
```

**Note:** The original documentation suggested bits 1-7, but testing confirmed the temperature is in bits 0-6 (mask `0x7F`). The app's decompiled code uses `substring(1, 8)` on a binary string with bit 7 at index 0, which is equivalent to masking with `0x7F`.

---

### AC Running Hours (Bytes 447-450)

- Byte 447: AC1 running hours (low byte)
- Byte 448: AC1 running hours (high byte)
- Byte 449: AC2 running hours (low byte)
- Byte 450: AC2 running hours (high byte)

Total hours = low + (high × 256)

---

### Wireless Sensors (Bytes 451-482)

32 sensor slots, one byte each. Sensors are mapped to zones: zone N uses sensor slots N*2 and N*2+1.

| Bit | Content |
|-----|---------|
| 7 | Available flag (1 = sensor present) |
| 6 | Low battery flag (1 = low battery) |
| 0-5 | Temperature value in Celsius |

**Parsing:**
```python
available = bool(byte & 0x80)    # bit 7
low_battery = bool(byte & 0x40)  # bit 6
temperature = byte & 0x3F        # bits 0-5, direct Celsius value
```

**Zone to Sensor Mapping:**
```python
# Each zone has up to 2 sensor slots
sensor1_index = zone_number * 2
sensor2_index = zone_number * 2 + 1

# Example: Zone 1 (TV Room) uses sensor slots 2 and 3
# Example: Zone 2 (Master) uses sensor slots 4 and 5
```

**Temperature Source Priority** (following app logic):
1. Touchpad assigned to the zone (if available and reporting)
2. Wireless sensor 1 for the zone (slot = zone * 2)
3. Wireless sensor 2 for the zone (slot = zone * 2 + 1)

**Note:** The original documentation had bits inverted. The app's decompiled code uses `substring(0, 1)` for available and `substring(1, 2)` for low battery on a binary string with bit 7 at index 0. This means bit 7 = available, bit 6 = low battery, and bits 0-5 = temperature. Wireless sensors are battery-powered and transmit intermittently.

---

### AirTouch Device ID (Bytes 483-490)

8 bytes containing the unique device identifier. The app uses the **lower nibble** (bits 0-3) of each byte, concatenated as decimal digits:

```python
device_id = ""
for i in range(8):
    byte = state[483 + i]
    nibble = byte & 0x0F  # bits 0-3 (low nibble)
    device_id += str(nibble)
```

---

### Service Contact Info (Bytes 361-382)

| Byte Range | Content |
|------------|---------|
| 361-370 | Contact name (10 ASCII characters) |
| 371-382 | Contact phone number (12 ASCII characters) |

---

## Implementation Guide

### Connection Parameters

| Parameter | Value | Source |
|-----------|-------|--------|
| Port | 8899 | `LocalConnection.sDevLocalPort` |
| Connect timeout | 5000ms (5 seconds) | `doConnect()` |
| Socket read timeout | 1000ms (1 second) | `doReceive()` |
| Read buffer size | 1024 bytes | `doReceive()` |
| State message size | 492 bytes | `DataFormatter` |
| Message accumulator buffer | 492 bytes | `DataFormatter.mBuffer` |

### Message Buffering (DataFormatter)

The app uses a `DataFormatter` class to handle message framing:

1. **Accumulation**: Incoming bytes are accumulated into a 492-byte buffer
2. **Framing**: Messages are processed when buffer reaches 492 bytes
3. **Partial reads**: Multiple TCP reads may be needed to complete one message

**Important**: TCP does not guarantee message boundaries. A single `recv()` call may return:
- Less than 492 bytes (partial message)
- Exactly 492 bytes (complete message)
- More than 492 bytes (complete message + start of next)

Your implementation must buffer incoming data and extract complete 492-byte messages:

```python
class MessageBuffer:
    def __init__(self):
        self.buffer = bytearray()

    def add_data(self, data: bytes) -> list[bytes]:
        """Add received data and return complete messages (492-byte preferred)."""
        self.buffer.extend(data)
        messages = []
        while True:
            # Prefer full local state frames
            if len(self.buffer) >= 492:
                messages.append(bytes(self.buffer[:492]))
                self.buffer = self.buffer[492:]
                continue

            # Handle 395-byte "internet mode" responses (bytes 100-107 are zero)
            if len(self.buffer) >= 395 and self.buffer[100:108] == b"\x00" * 8:
                messages.append(bytes(self.buffer[:395]))
                self.buffer = self.buffer[395:]
                continue

            break
        return messages
```

**Note**: The app also supports a 395-byte "internet mode response" message (detected when bytes 100-107 are all zero). For local connections, you should discard these and wait for a 492-byte frame.

### Connection Workflow

The original app uses this sequence (from `DeviceConnection.java` and `LocalConnection.java`):

1. **Create Socket** (`beforeConnect`)
   ```python
   sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   ```

2. **Connect with Timeout** (`doConnect`)
   ```python
   sock.settimeout(5.0)  # 5 second connect timeout
   sock.connect((DEVICE_IP, 8899))
   ```

3. **Send Initialization Message** (`afterConnect`)
   ```python
   init_msg = [0x55, 0x01, 0x0C, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
   init_msg.append(sum(init_msg) & 0xFF)
   sock.send(bytes(init_msg))
   ```

4. **Set Read Timeout and Receive Initial State** (`doReceive`)
   ```python
   sock.settimeout(1.0)  # 1 second read timeout
   state = sock.recv(1024)  # Buffer is 1024, but expect 492 bytes
   ```

5. **Enter Receive Loop**
   - Continue calling `recv()` in a loop
   - Handle `socket.timeout` exceptions (non-fatal, just retry)
   - Handle read returning -1 or 0 bytes (connection closed)
   - Feed chunks into a buffer/framer (see `MessageBuffer`) and process each 492-byte state message; ignore 395-byte internet-mode replies

### Important Implementation Notes

**Read Handling:**
- The app reads into a 1024-byte buffer but expects 492-byte messages
- A read timeout (1 second) is normal and not an error - just retry
- A read returning -1 bytes indicates connection was closed by remote
- A read returning 0 bytes after timeout is normal - continue loop
- Messages can be split or coalesced; always buffer and frame. 395-byte frames (internet responses) should be ignored in local mode.

**Send Handling:**
- Each send operation spawns a new thread in the original app
- For simpler implementations, sends can be synchronous
- Always expect a 492-byte state response after sending a command
- Most commands are relative (toggle/step). If other controllers change state concurrently, you must re-check state and possibly send multiple steps to reach a target (e.g., loop temp up/down until setpoint matches).

**Connection State Machine:**
```
DISCONNECT → CONNECTING → CONNECTED → DISCONNECTING → DISCONNECT
                ↑              ↓
                └──────────────┘ (on error)
```

### Error Handling

**SocketTimeoutException (read timeout):**
- Normal during idle periods - just continue the receive loop
- NOT an indication of connection failure

**Connection timeout (connect fails):**
- Device unreachable or wrong IP
- Retry connection or notify user
- Error message: "Connection timeout, please try again."

**Read returns -1:**
- Remote closed connection
- Transition to DISCONNECT state
- May need to reconnect

**Connection States:**
- `DISCONNECT`: Not connected
- `CONNECTING`: Connection in progress
- `CONNECTED`: Active connection
- `DISCONNECTING`: Closing connection

### Thread Safety

The original app uses separate threads for:
- **Connection Thread** (`ConnectProc`): Handles `doConnect()` and `afterConnect()`
- **Receive Thread** (`ReceiveProc`): Continuously calls `doReceive()` in a loop
- **Send Threads** (`SendDataRunable`): Each command spawns a new thread

For simpler implementations, you can use:
- **Synchronous**: Single thread, blocking sends and receives
- **Async/await**: Python asyncio with non-blocking sockets
- **Threading**: Separate send and receive threads with a message queue

---

## Byte Conversion Notes

### Java to Python

The original Android app uses Java's signed byte type (-128 to 127). When converting to Python:

| Java (signed) | Python (unsigned hex) | Decimal |
|---------------|----------------------|---------|
| -128 | 0x80 | 128 |
| -127 | 0x81 | 129 |
| -126 | 0x82 | 130 |
| -124 | 0x84 | 132 |
| -123 | 0x85 | 133 |
| -122 | 0x86 | 134 |
| -121 | 0x87 | 135 |
| -120 | 0x88 | 136 |
| -119 | 0x89 | 137 |
| -118 | 0x8A | 138 |
| -117 | 0x8B | 139 |
| -109 | 0x93 | 147 |
| -93  | 0xA3 | 163 |

Convert using: `unsigned = signed & 0xFF` or `unsigned = signed + 256 if signed < 0 else signed`

---

## Brand-Specific Considerations

### Gateway ID to Brand ID Mapping

The state message contains a "Gateway ID" (AC Unit ID) in bytes 439-440. The app translates this to a "Brand ID" for mode/fan remapping:

| Gateway ID | Brand ID | Notes |
|------------|----------|-------|
| 0 | 0 | Not available |
| 5 | 5 | |
| 8 | 1 | |
| 13 | 2 | |
| 15 | 6 | |
| 16 | 4 | |
| 18 | 14 | |
| 20 | 12 | |
| 21 | 7 | |
| 31 | 10 | |
| 34 | 2 | |
| 224 | 11 | Requires mode remapping |
| 225 | 13 | |
| 226 | 15 | Requires mode remapping |
| 255 | 2 | |

**Important:** The Brand ID in bytes 425-426 may already be the translated value. The raw AC Unit ID is in bytes 439-440.

**Recommendation:** Prefer the brand ID in bytes 425-426 for mode/fan remapping. If it is 0 or looks unrecognised, map the gateway ID (bytes 439-440) through the table above to derive the correct brand-specific behavior.

### Known Brand IDs

The app supports multiple AC brands with different command mappings:
- Brand 2: Special fan speed adjustment (+1 offset when supported=4)
- Brand 11: Special mode remapping required, error codes 109-116 filtered
- Brand 15: Different mode remapping, Auto fan = value 4

### Mode Remapping Example (Brand 11)

When sending mode commands to Brand 11 ACs:

| User Selection | Actual Byte Value |
|----------------|-------------------|
| Auto (0) | 0 |
| Heat (1) | 2 |
| Dry (2) | 3 |
| Fan (3) | 4 |
| Cool (4) | 1 |

### Determining Your Brand

1. Connect and receive 492-byte state
2. Check byte 425 (AC1) or byte 426 (AC2)
3. Parse as binary, convert to decimal
4. Use this brand ID for mode/fan remapping

---

## Advanced Features

### Complete Command Reference

| Byte 1 | Hex | Purpose | Method |
|--------|-----|---------|--------|
| 1 | 0x01 | Initialize connection | `GetInitMsg()` |
| -127 | 0x81 | Zone control (toggle/damper) | `SetZoneMessage()`, `SetFanMessage()` |
| -126 | 0x82 | Program time configuration | `setProgramMessage()` |
| -124 | 0x84 | AC timer set | `SetACTimeMessage()` |
| -123 | 0x85 | Zone naming | `SetNameMessage()` |
| -122 | 0x86 | AC control (power/temp/mode/fan) | `SetACOnOff()`, `SetNewTempMessage()`, etc. |
| -121 | 0x87 | Set owner name | `GetNewOwnerMessage()` |
| -120 | 0x88 | Activate favorite | `SetActiveFavMessage()` |
| -119 | 0x89 | Configure favorite zones | `SetFavZoneMessage()` |
| -118 | 0x8A | Set favorite name | `SetNewFavNameMessage()` |
| -117 | 0x8B | Synchronize time | `getSynchronizeTimeMsg()` |

---

### AC Timer Control (0x84)

The AC timer allows setting automatic ON/OFF times for each AC unit. Each AC has two timers: ON timer and OFF timer.

**Timer IDs:**
| ID | Function |
|----|----------|
| 1 | AC1 ON timer |
| 2 | AC1 OFF timer |
| 3 | AC2 ON timer |
| 4 | AC2 OFF timer |

**Set AC Timer:**
```
Byte 0:  0x55
Byte 1:  0x84
Byte 2:  0x0C
Byte 3:  Timer ID - 1 (0-3, see table above)
Byte 4:  0x00 = Set timer, 0x81 = Clear timer
Byte 5:  Hour (0-23, only used when setting)
Byte 6:  Minute (0-59, only used when setting)
Byte 7-11: 0x00
Byte 12: Checksum
```

**Examples:**
```python
# Set AC1 to turn ON at 6:30 AM
msg = [0x55, 0x84, 0x0C, 0x00, 0x00, 6, 30, 0, 0, 0, 0, 0]
msg.append(sum(msg) & 0xFF)

# Set AC1 to turn OFF at 10:00 PM (22:00)
msg = [0x55, 0x84, 0x0C, 0x01, 0x00, 22, 0, 0, 0, 0, 0, 0]
msg.append(sum(msg) & 0xFF)

# Clear AC2 ON timer
msg = [0x55, 0x84, 0x0C, 0x02, 0x81, 0, 0, 0, 0, 0, 0, 0]
msg.append(sum(msg) & 0xFF)
```

**State Message Timer Data (Bytes 415-422):**

The timer state is stored as 8 bytes, 2 bytes per timer:
| Bytes | Content |
|-------|---------|
| 415-416 | AC1 ON timer (byte 0: enabled flag bit 0, byte 1: time) |
| 417-418 | AC1 OFF timer |
| 419-420 | AC2 ON timer |
| 421-422 | AC2 OFF timer |

Timer byte format: If bit 0 of first byte = "0" (`(byte & 0x01) == 0`), timer is enabled. The second byte contains the time encoded as binary (hour * 4 + minute/15 approximately - see SetTime() in ACTimerActivity for exact parsing).

---

### Program Configuration (0x82)

The program scheduling system allows configuring automatic AC control based on day of week. Each program has 4 time slots for Mon-Fri, Saturday, and Sunday.

**Structure:**
- 4 Programs (1-4)
- 3 Day Types: Mon-Fri ("MF"), Saturday ("SAT"), Sunday ("SUN")
- 4 Time Slots per day type (1-4)
- Total: 4 × 3 × 4 = 48 possible schedule entries

**Array Index Calculation:**

The index for byte 3 is calculated as follows:
```
Base offset per program:
  Program 1: 0
  Program 2: 24
  Program 3: 48
  Program 4: 72

Day type offset (added to program base):
  Mon-Fri (MF): 0
  Saturday (SAT): 8
  Sunday (SUN): 16

Slot offset (added to day type):
  Slot 1: 0
  Slot 2: 2
  Slot 3: 4
  Slot 4: 6

Final formula:
  index = (program - 1) * 24 + day_offset + (slot - 1) * 2
```

**Example Indices:**
| Program | Day | Slot | Index |
|---------|-----|------|-------|
| 1 | MF | 1 | 0 |
| 1 | MF | 2 | 2 |
| 1 | MF | 3 | 4 |
| 1 | MF | 4 | 6 |
| 1 | SAT | 1 | 8 |
| 1 | SAT | 2 | 10 |
| 1 | SUN | 1 | 16 |
| 2 | MF | 1 | 24 |
| 2 | SAT | 1 | 32 |
| 3 | MF | 1 | 48 |
| 4 | MF | 1 | 72 |

**Set Program Time:**
```
Byte 0:  0x55
Byte 1:  0x82
Byte 2:  0x0C
Byte 3:  Array index (see calculation above)
Byte 4:  0x00 = Set time, 0x81 = Clear time slot
Byte 5:  Hour (0-23, only used when setting)
Byte 6:  Minute (0-59, only used when setting)
Byte 7-11: 0x00
Byte 12: Checksum
```

**Examples:**
```python
# Set Program 1, Mon-Fri, Slot 1 to 6:00 AM
# Index = (1-1)*24 + 0 + (1-1)*2 = 0
msg = [0x55, 0x82, 0x0C, 0, 0x00, 6, 0, 0, 0, 0, 0, 0]
msg.append(sum(msg) & 0xFF)

# Set Program 1, Saturday, Slot 2 to 8:30 AM
# Index = 0 + 8 + 2 = 10
msg = [0x55, 0x82, 0x0C, 10, 0x00, 8, 30, 0, 0, 0, 0, 0]
msg.append(sum(msg) & 0xFF)

# Clear Program 2, Sunday, Slot 1
# Index = 24 + 16 + 0 = 40
msg = [0x55, 0x82, 0x0C, 40, 0x81, 0, 0, 0, 0, 0, 0, 0]
msg.append(sum(msg) & 0xFF)
```

**Note:** Setting hour to -1 (0xFF) in the source code clears the slot, but using byte 4 = 0x81 is the proper clear command.

---

### Favorite Scenes

**Activate Favorite (0x88):**
```
Byte 0:  0x55
Byte 1:  0x88
Byte 2:  0x0C
Byte 3:  Favorite number (0-3) + 128
Byte 4:  0x80
Byte 5-11: 0x00
Byte 12: Checksum
```

**Configure Favorite Zones (0x89):**
```
Byte 0:  0x55
Byte 1:  0x89
Byte 2:  0x0C
Byte 3:  Favorite number (0-3) + 128
Byte 4:  Zone bitmap (zones 0-7, each bit = zone state)
Byte 5:  Zone bitmap (zones 8-15)
Byte 6-11: 0x00
Byte 12: Checksum
```

**Set Favorite Name (0x8A):**
```
Byte 0:  0x55
Byte 1:  0x8A
Byte 2:  0x0C
Byte 3:  Favorite number (0-3) + 128
Bytes 4-11: ASCII characters (8 chars max, space-padded)
Byte 12: Checksum
```

---

### Zone Naming (0x85)

**Set Zone Name:**
```
Byte 0:  0x55
Byte 1:  0x85
Byte 2:  0x0C
Byte 3:  (Zone number - 1) + 128
Bytes 4-11: ASCII characters (8 chars max, space-padded)
Byte 12: Checksum
```

**Example (Set zone 1 name to "Living"):**
```python
name_bytes = b'Living  '  # 8 chars, space padded
msg = [0x55, 0x85, 0x0C, 128] + list(name_bytes) + [0x00]
msg.append(sum(msg) & 0xFF)
```

---

### Time Synchronization (0x8B)

**Sync Device Time:**
```
Byte 0:  0x55
Byte 1:  0x8B
Byte 2:  0x0C
Byte 3:  Year (2-digit, e.g., 25 for 2025)
Byte 4:  Month - 1 (0-11)
Byte 5:  Day - 1 (0-30)
Byte 6:  Hour (0-23)
Byte 7:  Minute - 1 (0-58)
Byte 8-11: 0x00
Byte 12: Checksum
```

---

### Owner Name (0x87)

**Set Owner Name (21-byte message):**
```
Byte 0:  0x55
Byte 1:  0x87
Byte 2:  0x14 (20 decimal - message length)
Byte 3:  0x80
Bytes 4-19: ASCII owner name (16 chars, space-padded)
Byte 20: Checksum
```

**Note:** This is a 21-byte message, not the standard 13 bytes.

---

## Testing & Debugging

### Capture Verification Checklist
- Connect, send init, and capture the first 492-byte frame (Wireshark `tcp.port==8899`).
- Confirm length = 492; bytes 100-107 should **not** all be zero (otherwise it’s a 395-byte internet response).
- Note header bytes 0-1 (reserved) and ensure they’re consistent across frames for your device.
- Verify checksum on a known command (e.g., init checksum = `0x62`).
- Spot-check offsets: date/time (2-7), zone0 name (104-111), AC1 status (423), AC1 brand (425), AC1 mode (427), AC1 fan (429), AC1 setpoint (431), AC1 room temp (433), device ID low nibbles (483-490).
- For remap brands, compare the sent mode vs. reported mode (427/428) to confirm remap behavior.
- If you observe min/max setpoint limits in practice, record them alongside the brand ID for future reference.

### Packet Capture

Use Wireshark to verify protocol:
1. Filter: `tcp.port == 8899`
2. Capture during app usage
3. Compare hex dumps with this documentation
4. Verify checksums

### Debug Logging

The app logs all sent/received data:
```
Format: "read: len=X, HH HH HH ..." (hex bytes with spaces)
```

Enable similar logging in your implementation for troubleshooting.

### Common Issues

1. **No response after command**
   - Verify checksum calculation
   - Check byte order (little/big endian not applicable here, all single bytes)
   - Ensure connection initialized first

2. **Command has no effect**
   - Brand-specific remapping may be required
   - Check AC control mode (Basic vs Full)
   - Verify AC number (0 vs 1)

3. **Connection drops**
   - Implement socket timeout handling
   - Send periodic commands to keep alive
   - Handle DISCONNECTING state properly

---

## Source Code References

Key files from decompiled app:

- **MessageInBytes.java**: All command message formats
- **WifiCommService.java**: State message parsing (492-byte structure)
- **DataFormatter.java**: Message validation and routing
- **LocalConnection.java**: TCP connection management (port 8899)
- **DeviceConnection.java**: Abstract connection interface
- **WifiMainActivity.java**: Example command usage

---

## Example Python Implementation

```python
import socket
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import IntEnum

class ACMode(IntEnum):
    AUTO = 0
    HEAT = 1
    DRY = 2
    FAN = 3
    COOL = 4

class FanSpeed(IntEnum):
    AUTO = 0
    QUIET = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    POWERFUL = 5

class MessageBuffer:
    """Frame TCP stream into 492-byte messages, skipping 395-byte internet replies."""

    def __init__(self):
        self.buffer = bytearray()

    def add(self, data: bytes) -> List[bytes]:
        self.buffer.extend(data)
        messages: List[bytes] = []
        while True:
            if len(self.buffer) >= 492:
                messages.append(bytes(self.buffer[:492]))
                self.buffer = self.buffer[492:]
                continue
            if len(self.buffer) >= 395 and self.buffer[100:108] == b"\x00" * 8:
                # internet-mode response; collect then discard/ignore in caller
                messages.append(bytes(self.buffer[:395]))
                self.buffer = self.buffer[395:]
                continue
            break
        return messages

@dataclass
class ACState:
    """Parsed AC unit state."""
    power_on: bool = False
    mode: ACMode = ACMode.AUTO
    setpoint: int = 22
    room_temp: int = 22
    fan_speed: int = 0
    brand: int = 0
    has_error: bool = False
    error_code: int = 0

@dataclass
class ZoneState:
    """Parsed zone state."""
    name: str = ""
    is_on: bool = False
    damper_percent: int = 0
    is_spill: bool = False

class AirTouch3Client:
    """Client for AirTouch3 local TCP protocol."""

    # Command bytes
    CMD_INIT = 0x01
    CMD_ZONE = 0x81      # Zone control (was incorrectly 0x7F)
    CMD_AC = 0x86        # AC control

    # AC sub-commands (byte 4)
    AC_POWER = 0x80
    AC_TEMP_UP = 0xA3
    AC_TEMP_DOWN = 0x93
    AC_MODE = 0x81       # Mode command uses 0x81 in byte 4
    AC_FAN = 0x82

    # Brand IDs requiring mode remapping
    BRAND_REMAP_11 = 11
    BRAND_REMAP_15 = 15

    def __init__(self, host: str, port: int = 8899):
        self.host = host
        self.port = port
        self.socket: Optional[socket.socket] = None
        self.last_state: Optional[bytes] = None
        self.buffer = MessageBuffer()

    def _calculate_checksum(self, message: list) -> int:
        """Calculate checksum for message bytes 0-11."""
        return sum(message[0:12]) & 0xFF

    def _create_message(self, cmd: int, p1: int = 0, p2: int = 0, p3: int = 0) -> bytes:
        """Create a 13-byte command message."""
        msg = [0x55, cmd, 0x0C, p1, p2, p3, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
        msg[12] = self._calculate_checksum(msg)
        return bytes(msg)

    def _recv_state(self) -> Optional[bytes]:
        """Receive and return the next 492-byte state frame (skips 395-byte frames)."""
        if not self.socket:
            return None
        while True:
            try:
                chunk = self.socket.recv(1024)
                if not chunk:
                    return None
                for msg in self.buffer.add(chunk):
                    if len(msg) == 492:
                        return msg
                    # ignore 395-byte internet-mode replies
            except socket.timeout:
                continue

    def _send_and_receive(self, msg: bytes) -> Optional[bytes]:
        """Send command and receive state response."""
        if not self.socket:
            return None
        self.socket.send(msg)
        self.last_state = self._recv_state()
        return self.last_state

    def connect(self) -> bool:
        """Establish connection and send init message."""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(5.0)
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(1.0)

            # Send init message
            init_msg = self._create_message(self.CMD_INIT)
            self.last_state = self._send_and_receive(init_msg)
            return bool(self.last_state) and len(self.last_state) == 492

        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def ac_power_toggle(self, ac_num: int = 0) -> Optional[bytes]:
        """Toggle AC power (0 = AC1, 1 = AC2)."""
        msg = self._create_message(self.CMD_AC, ac_num, self.AC_POWER)
        return self._send_and_receive(msg)

    def temp_up(self, ac_num: int = 0) -> Optional[bytes]:
        """Increase temperature by 1°C."""
        msg = self._create_message(self.CMD_AC, ac_num, self.AC_TEMP_UP)
        return self._send_and_receive(msg)

    def temp_down(self, ac_num: int = 0) -> Optional[bytes]:
        """Decrease temperature by 1°C."""
        msg = self._create_message(self.CMD_AC, ac_num, self.AC_TEMP_DOWN)
        return self._send_and_receive(msg)

    def set_mode(self, mode: ACMode, ac_num: int = 0, brand: int = 0) -> Optional[bytes]:
        """Set AC mode. Brand is needed for mode remapping."""
        # Remap mode for certain brands
        mode_value = int(mode)
        if brand == self.BRAND_REMAP_11:
            remap = {0: 0, 1: 2, 2: 3, 3: 4, 4: 1}
            mode_value = remap.get(mode_value, mode_value)
        elif brand == self.BRAND_REMAP_15:
            remap = {0: 5, 1: 2, 2: 3, 3: 4, 4: 1}
            mode_value = remap.get(mode_value, mode_value)

        # Note: byte 4 is 0x81, mode goes in byte 5
        msg = self._create_message(self.CMD_AC, ac_num, self.AC_MODE, mode_value)
        return self._send_and_receive(msg)

    def set_fan_speed(self, speed: int, ac_num: int = 0) -> Optional[bytes]:
        """Set fan speed (0=Auto, 1=Quiet, 2=Low, 3=Med, 4=High, 5=Powerful)."""
        msg = self._create_message(self.CMD_AC, ac_num, self.AC_FAN, speed)
        return self._send_and_receive(msg)

    def zone_toggle(self, zone_num: int) -> Optional[bytes]:
        """Toggle zone on/off."""
        msg = self._create_message(self.CMD_ZONE, zone_num, 0x80)
        return self._send_and_receive(msg)

    def zone_damper_up(self, zone_num: int) -> Optional[bytes]:
        """Increase zone damper opening."""
        msg = self._create_message(self.CMD_ZONE, zone_num, 0x02, 0x01)
        return self._send_and_receive(msg)

    def zone_damper_down(self, zone_num: int) -> Optional[bytes]:
        """Decrease zone damper opening."""
        msg = self._create_message(self.CMD_ZONE, zone_num, 0x01, 0x01)
        return self._send_and_receive(msg)

    def parse_ac_state(self, ac_num: int = 0) -> ACState:
        """Parse AC state from last received message."""
        if not self.last_state or len(self.last_state) != 492:
            return ACState()

        data = self.last_state
        offset = ac_num  # 0 for AC1, 1 for AC2

        state = ACState()

        # Power and error (bytes 423-424)
        status_byte = data[423 + offset]
        state.power_on = bool(status_byte & 0x01)
        state.has_error = bool(status_byte & 0x02)

        # Brand (bytes 425-426)
        state.brand = data[425 + offset]

        # Mode (bytes 427-428, bits 0-6)
        mode_value = data[427 + offset] & 0x7F

        # Decode mode for remapped brands
        if state.brand in (self.BRAND_REMAP_11, self.BRAND_REMAP_15):
            decode = {0: 0, 1: 4, 2: 1, 3: 2, 4: 3}
            mode_value = decode.get(mode_value, mode_value)
        state.mode = ACMode(mode_value) if mode_value < 5 else ACMode.AUTO

        # Fan speed (bytes 429-430, bits 0-3)
        fan_byte = data[429 + offset]
        state.fan_speed = fan_byte & 0x0F

        # Setpoint (bytes 431-432, bits 0-6)
        setpoint_byte = data[431 + offset]
        state.setpoint = setpoint_byte & 0x7F

        # Room temp (bytes 433-434, full byte)
        room_temp = data[433 + offset]
        state.room_temp = room_temp if room_temp <= 127 else room_temp - 256

        # Error code (bytes 435-438)
        error_low = data[435 + (offset * 2)]
        error_high = data[436 + (offset * 2)]
        state.error_code = error_low + (error_high << 8)

        return state

    def parse_zone_state(self, zone_num: int) -> ZoneState:
        """Parse zone state from last received message."""
        if not self.last_state or len(self.last_state) != 492:
            return ZoneState()

        state = ZoneState()

        # Zone name (bytes 104-231, 8 chars per zone)
        name_start = 104 + (zone_num * 8)
        name_chars = [chr(self.last_state[i]) for i in range(name_start, name_start + 8)]
        state.name = ''.join(name_chars).strip()

        # Zone data (bytes 232-247)
        zone_data = self.last_state[232 + zone_num]
        state.is_on = bool(zone_data & 0x80)    # Bit 7 = ON/OFF
        state.is_spill = bool(zone_data & 0x40)  # Bit 6 = Spill

        # Damper opening (bytes 248-263, bits 0-6 * 5)
        damper_byte = self.last_state[248 + zone_num]
        damper_value = damper_byte & 0x7F
        state.damper_percent = damper_value * 5

        return state

    def get_zone_count(self) -> int:
        """Get total number of zones from state."""
        if not self.last_state or len(self.last_state) != 492:
            return 0
        return self.last_state[352]

    def disconnect(self):
        """Close connection."""
        if self.socket:
            self.socket.close()
            self.socket = None


# Usage example
if __name__ == "__main__":
    client = AirTouch3Client("192.168.1.100")

    if client.connect():
        print("Connected successfully")

        # Parse initial state
        ac1 = client.parse_ac_state(0)
        print(f"AC1: Power={'ON' if ac1.power_on else 'OFF'}, "
              f"Mode={ac1.mode.name}, Setpoint={ac1.setpoint}°C, "
              f"Room={ac1.room_temp}°C")

        # Get zone info
        zone_count = client.get_zone_count()
        print(f"Total zones: {zone_count}")

        for i in range(min(zone_count, 8)):
            zone = client.parse_zone_state(i)
            print(f"  Zone {i}: {zone.name} - "
                  f"{'ON' if zone.is_on else 'OFF'}, "
                  f"Damper: {zone.damper_percent}%")

        # Toggle AC power
        client.ac_power_toggle(0)
        ac1 = client.parse_ac_state(0)
        print(f"AC1 now: {'ON' if ac1.power_on else 'OFF'}")

        # Set to cooling mode (with brand for remapping)
        client.set_mode(ACMode.COOL, ac_num=0, brand=ac1.brand)

        client.disconnect()
```

---

## Home Assistant Integration Notes

For Home Assistant climate entity:

1. **State Polling**: Set up a background task to receive 492-byte messages
2. **Parse State**: Extract temperature, mode, power from specific bytes
3. **Command Methods**: Implement all control methods as HA service calls
4. **HVAC Modes**: Map HA modes to AirTouch protocol values
5. **Temperature**: Handle increment/decrement since direct set not available
6. **Zones**: Create separate switch entities for each zone

### Suggested Entity Structure

- **Climate Entity**: Per AC unit (AC1, AC2)
  - Current temperature
  - Target temperature
  - HVAC mode
  - Fan mode
  - On/off state

- **Switch Entities**: Per zone
  - On/off control
  - Damper percentage (if applicable)

- **Sensor Entities**: Per temperature sensor
  - Temperature reading
  - Battery level

---

## License & Disclaimer

This documentation is based on reverse engineering of the AirTouch 3 Android application. Use at your own risk. The protocol is proprietary and may change without notice. Always test in a safe environment before production use.

---

## Version History

- **v1.0** (2025-12-10): Initial documentation based on AirTouch3 v2.12 APK decompilation

---

## Additional Resources

- Original APK: AirTouch3_2.12_APKPure.apk
- Decompiled source location: `sources/au/com/polyaire/airtouch3/`
- Key classes: MessageInBytes.java, WifiCommService.java, LocalConnection.java
