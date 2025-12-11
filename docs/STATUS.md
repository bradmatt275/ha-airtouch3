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

## Resolved Issues
- **State bouncing fixed**: Protocol bit flags (bit0, bit7) were toggling between frames causing entity state flicker. Switched to damper-based detection which is stable.
- **Toggle bounce fixed**: Added optimistic updates with 5-second hold period to prevent UI bounce when toggling zones. The switch immediately reflects the expected state and ignores stale coordinator data until the device confirms.

## Remaining Items
- HACS tile icon not shown (would require submitting assets to HA brands repo).

## Recent Fixes
- Zone on/off heuristic: now uses damper position exclusively (< 100% = ON).
- Optimistic switch updates: 5-second hold prevents bounce after toggle commands.
- Options flow: now calls base initializer (fixed AttributeError).
- Damper parsing: reordered to avoid UnboundLocalError.
- Icon references removed from manifest; root icons resized but HACS uses HA brands repo.
