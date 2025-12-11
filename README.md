# AirTouch 3 Home Assistant Integration

Control your Polyaire AirTouch 3 air conditioning system locally from Home Assistant. The integration speaks the native TCP protocol (port 8899) to expose AC climate entities, zone switches, and temperature sensors.

## Features
- Climate entities for each AC unit (on/off, mode, fan speed, target temperature)
- Zone switches with damper percentage attributes
- Temperature sensors for AC rooms, touchpads, and wireless sensors
- Options for polling interval and enabling zones/sensors
- Tested with Home Assistant 2024.1+ (matches minimum in `hacs.json`)

## Installation

### HACS (recommended)
1. In Home Assistant, open HACS → Integrations.
2. Click the three dots → **Custom repositories**.
3. Add `https://github.com/mattbrady/ha-airtouch3` as category **Integration**.
4. Download the integration, then restart Home Assistant.

### Manual
1. Copy `custom_components/airtouch3` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Configuration
1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **AirTouch 3**.
3. Enter the device IP (and port if different from 8899).

### Options
- **Poll interval**: Seconds between refreshes (default 30).
- **Create temperature sensors**: Enable/disable creation of sensor entities.
- **Create zone switches**: Enable/disable zone switch entities.

## Troubleshooting
- **Cannot connect**: Verify IP, network reachability, and that the device is on the same LAN as Home Assistant.
- **No state received**: The controller may be busy; retry or reduce polling interval.
- **Stale entities**: Use the Configure button to adjust options or reload the integration.

## Notes
- Commands are toggles/steps; the integration checks state before sending where possible.
- Brand-specific mode/fan remapping is handled automatically based on the device state bytes.

## Credits
- Protocol based on reverse engineering of the AirTouch 3 Android app.
- Built for Home Assistant 2024.1+ compatibility.
