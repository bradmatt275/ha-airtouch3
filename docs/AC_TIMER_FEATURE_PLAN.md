# AC Timer Feature Plan

## Status

Planned. Protocol validation is required before implementation.

## Objective

Add local AirTouch 3 AC timer control to the Home Assistant integration. The
feature will expose the one-shot ON and OFF timers supported by each installed
AC unit.

AirTouch 3 supports up to two AC units, with two timers per unit:

| Timer index | Function |
|-------------|----------|
| 0 | AC1 ON timer |
| 1 | AC1 OFF timer |
| 2 | AC2 ON timer |
| 3 | AC2 OFF timer |

These timers are different from AirTouch programs. A timer executes once and
does not automatically repeat.

## Known Protocol Details

### Set or clear command

The AC timer command is a 13-byte message:

| Byte | Value |
|------|-------|
| 0 | `0x55` message header |
| 1 | `0x84` AC timer command |
| 2 | `0x0C` message length |
| 3 | Timer index (`0`-`3`) |
| 4 | `0x00` to set, `0x81` to clear |
| 5 | Hour (`0`-`23`) when setting |
| 6 | Minute (`0`-`59`) when setting |
| 7-11 | `0x00` |
| 12 | Sum of bytes 0-11, truncated to 8 bits |

Example: set the AC1 ON timer to 06:30:

```text
55 84 0C 00 00 06 1E 00 00 00 00 00 09
```

Example: clear the AC1 ON timer:

```text
55 84 0C 00 81 00 00 00 00 00 00 00 66
```

The exact command structure should still be confirmed during packet capture
before commands are sent from the integration.

### Returned state

Timer state is believed to occupy bytes 415-422 of the 492-byte state message:

| Bytes | Expected content |
|-------|------------------|
| 415-416 | AC1 ON timer |
| 417-418 | AC1 OFF timer |
| 419-420 | AC2 ON timer |
| 421-422 | AC2 OFF timer |

Each timer appears to use two bytes:

- One byte containing an enabled or unset flag.
- One byte containing an encoded time.

Current protocol notes suggest the time may be encoded in 15-minute units as
`hour * 4 + minute / 15`. This is not yet verified. The enabled flag's exact
polarity and any other flag bits also need confirmation.

## Packet Capture Required

### Goal

Confirm the set and clear commands and determine exactly how each timer is
represented in state bytes 415-422.

### Suggested setup

1. Capture traffic between the native AirTouch 3 app and the controller.
2. Filter for TCP port `8899`.
3. Save the full capture in PCAP or PCAPNG format.
4. Record the controller time and the action performed for each test.
5. Allow the app to receive an updated state message after every action.

Avoid including unrelated internet traffic where practical. Captures may
contain the AirTouch device ID and local network addresses, so review them
before sharing publicly.

### Minimum capture sequence

Start with all four timers cleared, then perform the following actions one at a
time:

| Test | Action | Purpose |
|------|--------|---------|
| 1 | Clear AC1 ON | Establish unset bytes and clear command |
| 2 | Set AC1 ON to 06:00 | Establish base hour encoding |
| 3 | Set AC1 ON to 06:15 | Identify minute encoding |
| 4 | Set AC1 ON to 06:30 | Identify minute encoding |
| 5 | Set AC1 ON to 06:45 | Identify minute encoding |
| 6 | Set AC1 ON to 23:59 | Test full minute precision and maximum values |
| 7 | Clear AC1 ON | Confirm flag transition |
| 8 | Set AC1 OFF to a known time | Confirm timer index 1 |
| 9 | Set AC2 ON to a known time | Confirm timer index 2, if AC2 is installed |
| 10 | Set AC2 OFF to a known time | Confirm timer index 3, if AC2 is installed |

If the native app only permits particular minute increments, use every
available increment for the 06:xx tests.

It would also be useful to let one near-future timer execute while capturing.
This should show whether the controller clears the timer immediately after it
fires and whether any temporary "active" state is reported.

### Capture notes template

For each action, record:

```text
Controller date/time:
AC unit:
Timer type: ON / OFF
Action: set / clear / fired
Selected timer time:
Outbound 0x84 command:
Returned bytes 415-422:
Additional observations:
```

### Questions the capture must answer

1. Does byte 4 use exactly `0x00` for set and `0x81` for clear?
2. Are timer indexes exactly `0` through `3` in the documented order?
3. Does the command carry ordinary hour and minute values?
4. Which bit indicates that a timer is set, and what is its polarity?
5. How are the returned hour and minute encoded across each two-byte pair?
6. Is returned time limited to 15-minute resolution?
7. Are any bits used for an active, elapsed, or pending state?
8. Does a fired timer clear itself in the next state message?
9. Does changing a timer always cause a fresh 492-byte state message?
10. What state bytes are returned for timer slots belonging to an absent AC2?

## Proposed Home Assistant Design

### Time entities

Create one `time` entity for every supported timer on each installed AC:

- `time.<device>_ac1_on_timer`
- `time.<device>_ac1_off_timer`
- `time.<device>_ac2_on_timer`
- `time.<device>_ac2_off_timer`

Only create AC2 entities when the second AC is present. The entity's native
value will be the configured local time, or `None` when the timer is unset.
Changing the time will send the timer set command.

### Clear controls

Create one clear `button` entity for each timer. A button is preferable to a
switch because setting a disabled timer requires a time value, and it is not
yet known whether the controller preserves the previous time after clearing.

The buttons should be configuration entities and named:

- AC1 ON timer clear
- AC1 OFF timer clear
- AC2 ON timer clear
- AC2 OFF timer clear

If the captured protocol shows that a cleared timer retains a reliable previous
time, paired enable switches can be reconsidered.

### Device association

Timer entities will be associated with the main AirTouch 3 device, consistent
with the existing AC controls. Entity names and unique IDs must include the AC
number and timer action.

### Time zone behaviour

The timer represents the AirTouch controller's local wall-clock time, not a UTC
timestamp. The existing time synchronization feature should remain independent,
but documentation should recommend synchronizing the controller clock if timer
execution is inaccurate.

## Data Model

Add an `AcTimerState` data class containing:

```python
@dataclass
class AcTimerState:
    timer_index: int
    ac_number: int
    action: AcTimerAction
    enabled: bool
    time: Optional[datetime.time]
```

Add an `AcTimerAction` enum with `ON` and `OFF` values. Add the parsed timer
collection to `SystemState`.

Keep the protocol representation out of the Home Assistant entity classes.
Encoding and decoding should be handled by `AirTouch3Client`.

## Client Changes

1. Add `CMD_AC_TIMER = 0x84` to `const.py`.
2. Add constants for the timer state offset, count, and bytes per timer.
3. Add a validated timer-index helper.
4. Add a pure command builder for setting and clearing timers.
5. Add async client methods:

   ```python
   async def set_ac_timer(
       self, ac_num: int, action: AcTimerAction, value: datetime.time
   ) -> bool:
       ...

   async def clear_ac_timer(
       self, ac_num: int, action: AcTimerAction
   ) -> bool:
       ...
   ```

6. Parse bytes 415-422 into `AcTimerState` objects.
7. Refresh and publish coordinator state after each successful command.
8. Log timer commands and returned raw timer bytes at debug level without
   logging unrelated state data.

Inputs must be validated before building a command:

- AC number is `0` or `1`.
- The selected AC exists.
- Hour is `0`-`23`.
- Minute is `0`-`59`, or a smaller verified set if the protocol is restricted.
- Seconds and microseconds are ignored or rejected consistently.

## Integration Changes

1. Add `Platform.TIME` to setup and unload.
2. Add `custom_components/airtouch3/time.py`.
3. Extend `button.py` with timer clear buttons.
4. Add translated entity names and icons to `strings.json` and
   `translations/en.json`.
5. Update the README feature list and protocol notes.
6. Mark the timer item complete in `docs/STATUS.md`.

No configuration-flow option is planned. Timer entities should be available
whenever a supported AC unit is detected.

## Testing Plan

### Unit tests

Add tests for:

- All four timer-index mappings.
- Exact bytes and checksum for known set commands.
- Exact bytes and checksum for all clear commands.
- Minimum and maximum valid times.
- Invalid AC numbers, hours, and minutes.
- Decoding every time sample obtained during packet capture.
- Enabled and cleared state decoding.
- Parsing systems with one and two AC units.
- Entity setup, names, unique IDs, and device association.
- Setting a `time` entity calls the correct client method.
- Pressing a clear button calls the correct client method.
- Coordinator refresh after set and clear operations.

Use captured byte sequences as anonymized test fixtures. Replace device IDs,
names, and network details while preserving the timer bytes and frame length.

### Hardware validation

After unit tests pass:

1. Set each available timer from Home Assistant.
2. Confirm the native app displays the same time.
3. Change each timer in the native app and confirm Home Assistant updates.
4. Clear each timer from both interfaces.
5. Confirm a timer executes once at the expected controller-local time.
6. Confirm the timer becomes unset after execution.
7. Test interaction with the existing controller time-sync button.
8. Confirm ordinary AC, zone, and sensor controls still update normally.

## Acceptance Criteria

The feature is ready for release when:

- Packet capture has resolved all open protocol questions.
- Home Assistant accurately displays set and unset timer states.
- Users can set and clear every timer belonging to an installed AC.
- The native app and Home Assistant remain synchronized in both directions.
- Timer execution occurs at the selected controller-local time.
- One-shot timers return to the unset state after firing.
- Invalid inputs cannot produce malformed protocol messages.
- Automated command, parser, and entity tests pass.
- Existing integration behaviour is unchanged.

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Incorrect state decoding | Do not implement decoding until capture samples confirm the format |
| Malformed commands interrupt controller communication | Test pure command bytes first and compare them with native-app captures |
| Controller clock differs from Home Assistant | Document controller-local semantics and retain the time-sync control |
| AC2 falsely detected | Reuse the integration's verified installed-AC detection |
| Timer fires before a slow polling refresh | Refresh coordinator state immediately after commands and retain normal polling |
| Native app changes timer concurrently | Treat controller state as authoritative on the next refresh |

## Out of Scope

- Repeating schedules.
- AirTouch program configuration (`0x82`).
- Zone timers.
- Countdown timers implemented only within Home Assistant.
- Automatically changing the AirTouch controller's date or time.

## Implementation Gate

Implementation should begin after a packet capture confirms:

1. At least one set command and one clear command.
2. The enabled flag polarity.
3. The complete returned time encoding.
4. State behaviour after a timer fires.

Once these are known, the remaining work is conventional client parsing,
Home Assistant entity setup, translations, and tests.
