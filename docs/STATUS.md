# AirTouch 3 Integration – Current Status (Dec 12, 2025)

## What's Working

### AC Control
- **AC Power Switch**: ON/OFF toggle for each AC unit
  - Uses bit 7 of status byte (mask `0x80`) - NOT bit 0
  - Optimistic updates with 10-second hold to prevent UI bounce
- **AC Mode Select**: Dropdown for Auto/Heat/Cool/Dry/Fan modes
  - Brand-specific mode remapping handled automatically
- **AC Fan Speed Select**: Dropdown with available fan speeds
  - Dynamic options based on AC's supported speeds
  - Correct encoding/decoding: Low=1, Medium=2, High=3, Powerful=4
- **AC Temperature Sensor**: Current room temperature reading

### Zone Control
- **Zone Switches**: ON/OFF toggle for each zone
  - Uses bit 7 of zone_data byte for ON/OFF state (matching Android app)
  - Optimistic updates with 5-second hold
  - Extra attributes: damper_percent, is_spill, active_program, sensor_source
- **Setpoint Up/Down Buttons**: Increment/decrement zone setpoint by 1°C
  - Only appears for zones with temperature sensors
  - Uses optimistic updates for immediate UI feedback
  - Simpler than number entity since AirTouch 3 only supports step commands
- **Setpoint Sensor**: Read-only display of current zone setpoint
  - Only appears for zones with temperature sensors
  - Supports optimistic updates (shows expected value immediately when buttons pressed)
- **Control Mode Select**: Dropdown to choose between Temperature and Fan modes
  - Only appears for zones with temperature sensors
  - Temperature = zone targets a setpoint, Fan = zone uses fixed damper %
  - Uses optimistic updates with 5-second hold
  - Dynamic icon (thermometer/fan) based on current mode
- **Damper Sensor**: Shows current damper opening percentage

### Temperature Sensors
- **Zone Temperature Sensors**: Per-zone temperature with source priority:
  1. Touchpad assigned to zone (if available)
  2. Wireless sensor 1 (slot = zone_number * 2)
  3. Wireless sensor 2 (slot = zone_number * 2 + 1)
- **Sensor Detection**: Zones detect temperature capability from:
  - Touchpad assignment (touchpad 1 or 2 assigned to zone)
  - Wireless sensor availability (bit 7 of sensor bytes at slots zone*2 and zone*2+1)
- **Parsing corrections**:
  - Touchpad: `byte & 0x7F` (bits 0-6)
  - Wireless: bit 7 = available, bit 6 = low battery, bits 0-5 = temperature

## Entity Structure

Zones are now represented as sub-devices for cleaner organization in Home Assistant:

### Main Device (AirTouch 3)
| Entity Type | Description |
|-------------|-------------|
| `switch` | AC power ON/OFF (per AC unit) |
| `select` | AC mode (Auto/Heat/Cool/Dry/Fan) |
| `select` | AC fan speed |
| `sensor` | AC room temperature |

### Zone Sub-Devices
| Entity Type | Description |
|-------------|-------------|
| `switch` | Zone power ON/OFF |
| `select` | Control Mode (Fan/Temperature) - zones with sensors only |
| `button` | Setpoint Up (+1°C) - zones with sensors only |
| `button` | Setpoint Down (-1°C) - zones with sensors only |
| `sensor` | Setpoint (current target temperature) - zones with sensors only |
| `sensor` | Zone temperature |
| `sensor` | Zone damper percentage |

**Note**: The `climate` entity was removed in favor of simpler switch/select/button entities because the AirTouch 3 doesn't fit the standard HVAC model well (separate power toggle, temperature in steps only, per-zone temperature control).

## Key Protocol Discoveries

### CRITICAL: Zone Data Indexing

The AirTouch 3 protocol uses TWO different indexing schemes for zone data, which caused many bugs:

1. **`data_index`**: Derived from Group Data bytes (offset 264+). Used for:
   - Zone data byte (offset 232 + data_index)
   - Damper percentage value (bits 0-6 of byte at offset 248 + data_index)

2. **`zone_num`**: Sequential zone number (0, 1, 2...). Used for:
   - Temperature control mode flag (bit 7 of byte at offset 248 + zone_num)
   - Feedback/setpoint byte (offset 280 + zone_num)
   - Zone toggle commands (zone_num is sent in the command)

**Why this matters**: For zones where `data_index != zone_num`, using the wrong index gives incorrect values. For example:
- Zone 0 (Living): data_index=0, zone_num=0 → same, no issue
- Zone 1 (TV room): data_index=2, zone_num=1 → DIFFERENT!
- Zone 2 (Master): data_index=3, zone_num=2 → DIFFERENT!

This was verified via Wireshark captures comparing Android app state reads.

### AC Power Status (Byte 423/424)
- **Bit 7** contains power state, NOT bit 0
- The Android app uses `toFullBinaryString()` which creates MSB-first strings
- When app does `substring(0,1)`, it's checking bit 7

### Zone State
- **Bit 7 (0x80)** of zone_data byte indicates ON/OFF state (1=ON, 0=OFF)
- **Bit 6 (0x40)** indicates spill mode
- The Android app uses bit 7 for zone ON/OFF determination (WifiCommService.java lines 1178-1183)
- Damper position reflects the airflow percentage but does NOT indicate ON/OFF state
- **Note**: Zone state reflects the *requested* state, not whether air is currently flowing. A zone can show ON even if the AC is off - this means the zone will receive air when the AC turns on.

### Setpoint Parsing
- Located at offset 280 + **zone_num** (NOT data_index!)
- Feedback byte structure:
  - Bits 5-7: Sensor source (0 = no sensor, >0 = has sensor)
  - Bits 0-4: Setpoint raw value
- Setpoint formula: `(feedback & 0x1F) + 1` if sensor_source > 0, else None
- The +1 offset was verified by testing (28°C stored as 27 in bits 0-4)

### Fan Speed Encoding
- Auto = 0 (or 4 for Brand 15)
- Low = 1, Medium = 2, High = 3, Powerful = 4
- Brand 2 with supported=4: add 1 to value

### Zone Commands
All zone commands use `zone_num` (not data_index):
- Toggle mode: `55 81 0c [zone_num] 80 01 00 00 00 00 00 00 [checksum]`
- Value up: `55 81 0c [zone_num] 02 01 00 00 00 00 00 00 [checksum]`
- Value down: `55 81 0c [zone_num] 01 01 00 00 00 00 00 00 [checksum]`

## Resolved Issues

1. **Zone state bouncing**: Fixed by using bit 7 of zone_data (matching Android app logic)
2. **Toggle bounce in UI**: Fixed with optimistic updates (5s zones, 10s AC power)
3. **AC power showing wrong state**: Fixed by checking bit 7 instead of bit 0
4. **Touchpad temp 77°C instead of 26°C**: Fixed bit parsing (`byte & 0x7F`)
5. **Wireless sensor wrong temps**: Fixed bit layout (7=available, 6=low_battery, 0-5=temp)
6. **Fan speed off-by-one**: Fixed encoding/decoding to match app's `formatFanSpeed()`
7. **Climate entity power issues**: Replaced with simpler switch/select entities
8. **Zone control mode not updating for some zones**: Fixed by using `zone_num` instead of `data_index` for temperature control mode flag
9. **Zone setpoint reading wrong values**: Fixed by using `zone_num` instead of `data_index` for feedback/setpoint byte
10. **Setpoint number entity causing runaway commands**: Replaced with simpler up/down buttons since AirTouch 3 only supports step commands (not direct value setting)

## Files Modified

- `client.py` - Protocol parsing with corrected bit masks and indexing, zone control commands
  - **Critical**: Uses `zone_num` for temperature_control flag and setpoint, `data_index` for damper percentage
- `switch.py` - Zone switches + AC power switch with optimistic updates
- `select.py` - AC mode/fan speed selects + Zone control mode select (Fan/Temperature)
- `sensor.py` - Zone temperature, damper, and setpoint sensors with source priority and optimistic updates
- `button.py` - Setpoint up/down buttons with optimistic updates
- `models.py` - Added `temperature_control` and `has_sensor` fields to ZoneState
- `const.py` - Added zone command constants (ZONE_TOGGLE, ZONE_DAMPER_UP, ZONE_DAMPER_DOWN, etc.)
- `coordinator.py` - Uses `refresh_state()` for fresh data
- `__init__.py` - Platform setup (switch, select, sensor, button)

## Known Issues

- **State inconsistencies**: Toggle commands sometimes don't take effect, possibly due to timing or protocol quirks. May need retry logic or adjusted optimistic hold periods.
- **Toggle protocol challenges**: The AirTouch 3 uses toggle commands rather than explicit on/off, which can cause issues if state gets out of sync.

## Future Improvements

### Potential Additions
- [ ] Damper percentage control (up/down buttons similar to setpoint)
- [ ] AC timer configuration entities
- [ ] Program/schedule configuration
- [ ] Favorite scene activation
- [ ] Retry logic for failed toggle commands

### Nice to Have
- [ ] Submit icons to HA brands repo for HACS tile display
- [ ] Add diagnostics dump for troubleshooting
- [ ] Unit tests for protocol parsing

## Development Notes

### Debug Logging
Enable in `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.airtouch3: debug
```

### Key Log Lines
- `AC X: status_byte=0xXX (...), power_on=X (bit7)` - AC status parsing
- `Zone X: ... damper_raw=X (X%)` - Zone state with damper position
- `Zone X: feedback[data_idx=X]=0xXX setpoint=X, feedback[zone_num]=0xXX setpoint=X` - Setpoint parsing comparison (for debugging indexing issues)
- `Touchpad X: ... temp_value=X` - Touchpad temperature parsing
- `Wireless Sensor X: ... temp=X` - Wireless sensor parsing
- `Setpoint UP/DOWN pressed for zone X` - Button press events
- `Zone X value UP/DOWN command: XX XX XX...` - Raw command bytes being sent

### Testing Methodology for Index Issues
If you suspect an indexing issue (data_index vs zone_num), add debug logging that reads from both indexes and compares:
```python
LOGGER.debug(
    "Zone %d: value[data_idx=%d]=0x%02x, value[zone_num]=0x%02x",
    zone_num, data_index, data[offset + data_index], data[offset + zone_num]
)
```
Then compare with actual values shown in the Android app or on the physical unit.

### Wireshark Capture Tips
To capture and analyze AirTouch 3 protocol:
1. Filter by `tcp.port == 8899`
2. The state message is 492 bytes
3. Commands are 13 bytes starting with `55`
4. Follow TCP stream and export as hex to analyze byte offsets

### Reinstalling After Changes
After code changes, you may need to:
1. Restart Home Assistant
2. Delete and re-add the integration (if entity structure changed)
