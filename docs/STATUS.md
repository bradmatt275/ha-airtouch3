# AirTouch 3 Integration – Current Findings (Dec 11, 2025)

## Implemented
- Async client with protocol parsing, high-nibble zone mapping, brand remaps.
- Config/Options flow (crash fixed).
- Climate, switch, sensor entities; HACS metadata in place (manifest icon refs removed).

## Zone Control
- Commands now target the correct zones after group mapping fixes.

## Zone State Parsing (current behavior)
- Data index: high nibble of group byte (bytes 264–279); fallback to zone index if out of range.
- On/off: determined by **damper position only** – damper < 100% = ON, damper = 100% = OFF. Protocol bit flags (both high and low nibble) proved unreliable and noisy across frames.
- Spill: high_spill flag (bit 6) combined with damper = 100%.
- Debug logging dumps zone/group bytes for verification.

## Temperature Sensors
- **Zone temperature sensors**: Each zone gets a temperature entity that follows the app's priority logic:
  1. Touchpad assigned to zone (if available)
  2. Wireless sensor 1 for zone (slot = zone_number * 2)
  3. Wireless sensor 2 for zone (slot = zone_number * 2 + 1)
- **Touchpad parsing**: Temperature in bits 0-6 (`byte & 0x7F`).
- **Wireless sensor parsing**: Bit 7 = available, bit 6 = low battery, bits 0-5 = temperature (`byte & 0x3F`).
- Extra attributes include `source` (e.g., "touchpad1", "wireless_3") and `low_battery` flag.
- Zones without sensors show as "Unavailable".

## Resolved Issues
- **State bouncing fixed**: Protocol bit flags (bit0, bit7) were toggling between frames causing entity state flicker. Switched to damper-based detection which is stable.
- **Toggle bounce fixed**: Added optimistic updates with 5-second hold period to prevent UI bounce when toggling zones. The switch immediately reflects the expected state and ignores stale coordinator data until the device confirms.
- **Sensor temperatures fixed**: Touchpad showed 77°C instead of 26°C due to incorrect bit parsing. Fixed by using `byte & 0x7F` for touchpads and `byte & 0x3F` for wireless sensors, with correct available/low_battery flag parsing (bits 7 and 6).
- **Sensor entity cleanup**: Removed 32 individual wireless sensor entities. Now uses per-zone temperature sensors that automatically select the best available source.

## Remaining Items
- HACS tile icon not shown (would require submitting assets to HA brands repo).

## Recent Fixes
- Zone temperature sensors: follow app logic (touchpad priority, then wireless sensors).
- Touchpad temperature parsing: `byte & 0x7F` (was incorrectly shifting).
- Wireless sensor parsing: bit 7 = available, bit 6 = low battery, bits 0-5 = temperature.
- Zone on/off heuristic: now uses damper position exclusively (< 100% = ON).
- Optimistic switch updates: 5-second hold prevents bounce after toggle commands.
- Options flow: now calls base initializer (fixed AttributeError).
- Damper parsing: reordered to avoid UnboundLocalError.
- Icon references removed from manifest; root icons resized but HACS uses HA brands repo.
