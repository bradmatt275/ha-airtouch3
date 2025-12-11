# AirTouch 3 Integration – Current Status (Dec 11, 2025)

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

### Zone Control
- **Zone Switches**: ON/OFF toggle for each zone
  - Uses damper position for state detection (< 100% = ON)
  - Optimistic updates with 5-second hold
  - Extra attributes: damper_percent, is_spill, active_program, sensor_source

### Temperature Sensors
- **Zone Temperature Sensors**: Per-zone temperature with source priority:
  1. Touchpad assigned to zone (if available)
  2. Wireless sensor 1 (slot = zone_number * 2)
  3. Wireless sensor 2 (slot = zone_number * 2 + 1)
- **Parsing corrections**:
  - Touchpad: `byte & 0x7F` (bits 0-6)
  - Wireless: bit 7 = available, bit 6 = low battery, bits 0-5 = temperature

## Entity Structure

After recent refactoring, the integration now uses:

| Entity Type | Per | Description |
|-------------|-----|-------------|
| `switch` | Zone | Zone ON/OFF control |
| `switch` | AC | AC power ON/OFF |
| `select` | AC | AC mode (Auto/Heat/Cool/Dry/Fan) |
| `select` | AC | AC fan speed |
| `sensor` | Zone | Zone temperature (optional) |

**Note**: The `climate` entity was removed in favor of simpler switch/select entities because the AirTouch 3 doesn't fit the standard HVAC model well (separate power toggle, temperature in steps only, per-zone temperature control).

## Key Protocol Discoveries

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

### Fan Speed Encoding
- Auto = 0 (or 4 for Brand 15)
- Low = 1, Medium = 2, High = 3, Powerful = 4
- Brand 2 with supported=4: add 1 to value

## Resolved Issues

1. **Zone state bouncing**: Fixed by using bit 7 of zone_data (matching Android app logic)
2. **Toggle bounce in UI**: Fixed with optimistic updates (5s zones, 10s AC power)
3. **AC power showing wrong state**: Fixed by checking bit 7 instead of bit 0
4. **Touchpad temp 77°C instead of 26°C**: Fixed bit parsing (`byte & 0x7F`)
5. **Wireless sensor wrong temps**: Fixed bit layout (7=available, 6=low_battery, 0-5=temp)
6. **Fan speed off-by-one**: Fixed encoding/decoding to match app's `formatFanSpeed()`
7. **Climate entity power issues**: Replaced with simpler switch/select entities

## Files Modified

- `client.py` - Protocol parsing with corrected bit masks
- `switch.py` - Zone switches + AC power switch with optimistic updates
- `select.py` - NEW: AC mode and fan speed select entities
- `sensor.py` - Zone temperature sensors with source priority
- `coordinator.py` - Uses `refresh_state()` for fresh data
- `__init__.py` - Platform setup (switch, select, sensor)

## Future Improvements

### Potential Additions
- [ ] Per-zone temperature setpoint control (requires temp step commands)
- [ ] AC timer configuration entities
- [ ] Program/schedule configuration
- [ ] Favorite scene activation
- [ ] Damper percentage control (cover entity?)

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
- `Touchpad X: ... temp_value=X` - Touchpad temperature parsing
- `Wireless Sensor X: ... temp=X` - Wireless sensor parsing

### Reinstalling After Changes
After code changes, you may need to:
1. Restart Home Assistant
2. Delete and re-add the integration (if entity structure changed)
