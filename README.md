# AirTouch 3 Home Assistant Integration

Control your Polyaire AirTouch 3 air conditioning system locally from Home Assistant. The integration speaks the native TCP protocol (port 8899) to expose AC climate entities, zone controls, and temperature sensors.

## Features

### AC Unit Controls
- Power switch for each AC unit
- Mode selection (Auto, Heat, Dry, Fan, Cool)
- Fan speed selection (Auto, Quiet, Low, Medium, High, Powerful - based on unit capabilities)
- Temperature sensor showing current room temperature

### Zone Controls
Each zone is represented as a sub-device with the following entities:
- **Power switch**: Turn zone on/off
- **Setpoint**: Adjust temperature setpoint (°C) or damper opening (%) depending on control mode
- **Temp Control switch**: Toggle between temperature and percentage control modes (only for zones with temperature sensors)
- **Temperature sensor**: Current zone temperature (from touchpad or wireless sensor)
- **Damper sensor**: Current damper opening percentage

### Additional Features
- Automatic detection of wireless temperature sensors
- Support for touchpad temperature readings
- Low battery alerts for wireless sensors (via sensor attributes)
- Configurable polling interval
- Options to enable/disable zone and sensor entities

## Installation

### HACS (recommended)
1. In Home Assistant, open HACS → Integrations.
2. Click the three dots → **Custom repositories**.
3. Add `https://github.com/bradmatt275/ha-airtouch3` as category **Integration**.
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
- The AirTouch 3 protocol uses toggle commands rather than explicit on/off. The integration uses optimistic state handling to provide responsive UI feedback.
- Zone setpoint adjustments use increment/decrement commands stepped until the target is reached.
- Brand-specific mode/fan remapping is handled automatically based on the device state bytes.
- Zones are grouped as sub-devices under the main AirTouch 3 device for cleaner organization.

## Credits
- Protocol based on reverse engineering of the AirTouch 3 Android app.
- Built for Home Assistant 2024.1+ compatibility.
