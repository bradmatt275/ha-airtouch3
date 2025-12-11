# AirTouch 3 Integration – Current Findings (Dec 11, 2025)

## Implemented
- Async client with protocol parsing, high-nibble zone mapping, brand remaps.
- Config/Options flow (crash fixed).
- Climate, switch, sensor entities; HACS metadata in place (manifest icon refs removed).

## Zone Control
- Commands now target the correct zones after group mapping fixes.

## Zone State Parsing (current behavior)
- Data index: high nibble of group byte (bytes 264–279); fallback to zone index if out of range.
- On/off: true if any on flag (bit0 or bit7) **or** damper < 90% (device reports ~100% when off, ~30–60% when on). Spill: bit1 or bit6.
- Debug logging dumps zone/group bytes for verification.

## Observed Issues
- Entity states still bounce: TV room/Master switches sometimes revert after toggling; initial load shows incorrect on/off for some zones.
- Logs show zone_data changing between frames (e.g., Master 0x83 → 0x03) and damper values (35–60%) when on; low-bit on flags may be noisy.
- HACS tile icon not shown (would require submitting assets to HA brands repo).

## Next Steps (when resuming)
1) Refine on/off heuristic:
   - Consider using only high-bit on (bit7) with optional damper threshold debounce.
   - Alternatively, require consistent state across two polls to reduce bounce.
2) Cross-check WifiCommService parsing for your brand to confirm which bits drive on/off and spill.
3) Verify initial load: ensure first refresh runs after connection, and possibly force a second poll before setting entity state.
4) If desired, add a user option to set damper-on threshold or choose high-bit-only.

## Recent Fixes
- Options flow: now calls base initializer (fixed AttributeError).
- Damper parsing: reordered to avoid UnboundLocalError.
- Icon references removed from manifest; root icons resized but HACS uses HA brands repo.
