"""Async TCP client for the AirTouch 3 protocol."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from typing import Iterable, List, Optional

from . import const
from .models import AcMode, AcState, FanSpeed, SensorState, SystemState, TouchpadState, ZoneState

LOGGER = logging.getLogger(__name__)


GATEWAY_BRAND_MAP: dict[int, int] = {
    0: 0,
    5: 5,
    8: 1,
    13: 2,
    15: 6,
    16: 4,
    18: 14,
    20: 12,
    21: 7,
    31: 10,
    34: 2,
    224: 11,
    225: 13,
    226: 15,
    255: 2,
}


class MessageBuffer:
    """Accumulates TCP stream data into framed messages."""

    def __init__(self) -> None:
        self.buffer = bytearray()

    def add_data(self, data: bytes) -> list[bytes]:
        """Add data and return complete messages."""
        self.buffer.extend(data)
        messages: list[bytes] = []
        while True:
            if (
                len(self.buffer) >= const.INTERNET_MSG_SIZE
                and self.buffer[100:108] == b"\x00" * 8
            ):
                LOGGER.debug("Dropping internet-mode frame (%s bytes)", const.INTERNET_MSG_SIZE)
                del self.buffer[: const.INTERNET_MSG_SIZE]
                continue

            if len(self.buffer) >= const.STATE_MSG_SIZE:
                messages.append(bytes(self.buffer[: const.STATE_MSG_SIZE]))
                del self.buffer[: const.STATE_MSG_SIZE]
                continue

            break
        return messages


class AirTouch3Client:
    """Async client for AirTouch 3 device communication."""

    def __init__(self, host: str, port: int = const.DEFAULT_PORT) -> None:
        """Initialize the client."""
        self.host = host
        self.port = port
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._buffer = MessageBuffer()
        self._lock = asyncio.Lock()
        self._latest_state: Optional[SystemState] = None

    @property
    def connected(self) -> bool:
        """Return True if socket is connected."""
        return self.writer is not None and not self.writer.is_closing()

    async def connect(self) -> bool:
        """Establish TCP connection and send init message."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=const.CONNECT_TIMEOUT,
            )
        except (asyncio.TimeoutError, OSError) as err:
            LOGGER.error("Failed to connect to AirTouch 3 at %s:%s: %s", self.host, self.port, err)
            self.reader = None
            self.writer = None
            return False

        init_msg = self._create_command(const.CMD_INIT)
        response = await self._send_command(init_msg)
        if response is None:
            LOGGER.error("No state received after init")
            await self.disconnect()
            return False

        self._latest_state = response
        return True

    async def disconnect(self) -> None:
        """Close connection."""
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        self.reader = None
        self.writer = None

    async def get_state(self) -> Optional[SystemState]:
        """Return the most recent state, fetching if needed."""
        if not self.connected:
            if not await self.connect():
                return None

        if self._latest_state:
            return self._latest_state

        return await self._wait_for_state()

    async def refresh_state(self) -> Optional[SystemState]:
        """Force a fresh state fetch by sending init command."""
        if not self.connected:
            if not await self.connect():
                return None

        init_msg = self._create_command(const.CMD_INIT)
        return await self._send_command(init_msg)

    async def ac_power_toggle(self, ac_num: int) -> bool:
        """Toggle AC power."""
        return await self._send_ac_command(ac_num, const.AC_POWER_TOGGLE, 0)

    async def ac_set_mode(self, ac_num: int, mode: AcMode) -> bool:
        """Set AC mode, handling brand remapping."""
        brand = self._get_brand(ac_num)
        mode_value = self._encode_mode(mode, brand)
        return await self._send_ac_command(ac_num, const.AC_MODE, mode_value)

    async def ac_set_fan_speed(self, ac_num: int, speed: FanSpeed) -> bool:
        """Set fan speed with brand handling."""
        brand = self._get_brand(ac_num)
        supported = self._get_supported_fan_bitmap(ac_num)
        value = self._encode_fan_speed(speed, brand, supported)
        return await self._send_ac_command(ac_num, const.AC_FAN, value)

    async def ac_temp_up(self, ac_num: int) -> bool:
        """Increase setpoint by 1°C."""
        return await self._send_ac_command(ac_num, const.AC_TEMP_UP, 0)

    async def ac_temp_down(self, ac_num: int) -> bool:
        """Decrease setpoint by 1°C."""
        return await self._send_ac_command(ac_num, const.AC_TEMP_DOWN, 0)

    async def ac_set_temperature(self, ac_num: int, target: int) -> bool:
        """Loop increment/decrement to reach target setpoint."""
        if target < const.MIN_TEMP or target > const.MAX_TEMP:
            LOGGER.warning("Target temperature %s outside range", target)
            return False

        for _ in range(30):
            state = await self.get_state()
            if state is None:
                return False
            current = state.ac_units[ac_num].setpoint
            if current == target:
                return True
            if current < target:
                if not await self.ac_temp_up(ac_num):
                    return False
            else:
                if not await self.ac_temp_down(ac_num):
                    return False
        LOGGER.error("Failed to reach target temperature %s", target)
        return False

    async def zone_toggle(self, zone_index: int) -> bool:
        """Toggle zone on/off."""
        command = self._create_command(const.CMD_ZONE, zone_index, const.ZONE_TOGGLE, 0)
        return (await self._send_command(command)) is not None

    async def zone_set_damper(self, zone_index: int, target_percent: int) -> bool:
        """Adjust damper via increment/decrement commands."""
        target = min(100, max(0, target_percent))
        for _ in range(25):
            state = await self.get_state()
            if state is None:
                return False
            if zone_index >= len(state.zones):
                return False
            current = state.zones[zone_index].damper_percent
            if current == target:
                return True
            if current < target:
                cmd = self._create_command(const.CMD_ZONE, zone_index, const.ZONE_DAMPER_UP, 1)
            else:
                cmd = self._create_command(const.CMD_ZONE, zone_index, const.ZONE_DAMPER_DOWN, 1)
            if await self._send_command(cmd) is None:
                return False
        LOGGER.error("Failed to reach target damper %s", target_percent)
        return False

    async def zone_value_up(self, zone_index: int) -> Optional[SystemState]:
        """Increase zone value (temperature or damper percent, depending on mode).

        Returns the updated SystemState, or None on failure.
        """
        command = self._create_command(
            const.CMD_ZONE, zone_index, const.ZONE_DAMPER_UP, const.ZONE_VALUE_ADJUST
        )
        LOGGER.debug(
            "Zone %d value UP command: %s",
            zone_index,
            " ".join(f"{b:02x}" for b in command),
        )
        result = await self._send_command(command)
        if result:
            LOGGER.debug(
                "Zone %d after UP: setpoint=%s, damper=%d%%",
                zone_index,
                result.zones[zone_index].setpoint,
                result.zones[zone_index].damper_percent,
            )
        return result

    async def zone_value_down(self, zone_index: int) -> Optional[SystemState]:
        """Decrease zone value (temperature or damper percent, depending on mode).

        Returns the updated SystemState, or None on failure.
        """
        command = self._create_command(
            const.CMD_ZONE, zone_index, const.ZONE_DAMPER_DOWN, const.ZONE_VALUE_ADJUST
        )
        LOGGER.debug(
            "Zone %d value DOWN command: %s",
            zone_index,
            " ".join(f"{b:02x}" for b in command),
        )
        result = await self._send_command(command)
        if result:
            LOGGER.debug(
                "Zone %d after DOWN: setpoint=%s, damper=%d%%",
                zone_index,
                result.zones[zone_index].setpoint,
                result.zones[zone_index].damper_percent,
            )
        return result

    async def zone_toggle_mode(self, zone_index: int) -> bool:
        """Toggle zone between temperature and percentage control modes."""
        command = self._create_command(
            const.CMD_ZONE, zone_index, const.ZONE_TOGGLE, const.ZONE_MODE_TOGGLE
        )
        LOGGER.debug(
            "Zone %d mode toggle command: %s",
            zone_index,
            " ".join(f"{b:02x}" for b in command),
        )
        return (await self._send_command(command)) is not None

    async def zone_set_value(self, zone_index: int, target: int, is_temperature: bool) -> bool:
        """Set zone value (temperature or damper percent) via increment/decrement.

        Args:
            zone_index: Zone index
            target: Target value (temperature in °C or damper percent)
            is_temperature: True if setting temperature, False for damper percent
        """
        mode_str = "temperature" if is_temperature else "damper"
        LOGGER.debug("zone_set_value: zone=%d, target=%d, mode=%s", zone_index, target, mode_str)

        # Get initial state
        state = await self.get_state()
        if state is None:
            LOGGER.error("zone_set_value: Failed to get initial state")
            return False

        max_iterations = 25 if is_temperature else 25
        for iteration in range(max_iterations):
            if zone_index >= len(state.zones):
                LOGGER.error("zone_set_value: Zone index %d out of range", zone_index)
                return False
            zone = state.zones[zone_index]

            # Get current value based on mode
            if is_temperature:
                if zone.setpoint is None:
                    LOGGER.error("Zone %s has no temperature sensor", zone_index)
                    return False
                current = zone.setpoint
            else:
                current = zone.damper_percent

            LOGGER.debug(
                "zone_set_value: iteration=%d, current=%d, target=%d",
                iteration, current, target
            )

            if current == target:
                LOGGER.debug("zone_set_value: Target reached!")
                return True

            if current < target:
                LOGGER.debug("zone_set_value: Sending value UP command")
                state = await self.zone_value_up(zone_index)
                if state is None:
                    LOGGER.error("zone_set_value: zone_value_up failed")
                    return False
            else:
                LOGGER.debug("zone_set_value: Sending value DOWN command")
                state = await self.zone_value_down(zone_index)
                if state is None:
                    LOGGER.error("zone_set_value: zone_value_down failed")
                    return False

        LOGGER.error("Failed to reach target value %s for zone %s", target, zone_index)
        return False

    async def sync_time(self, timestamp: datetime | None = None) -> bool:
        """Send a time synchronisation command (fire-and-forget)."""
        when = timestamp or datetime.now()
        command = self._create_time_sync_command(when)
        if not self.connected:
            if not await self.connect():
                return False

        async with self._lock:
            assert self.writer
            try:
                self.writer.write(command)
                await self.writer.drain()
            except Exception as err:  # noqa: BLE001
                LOGGER.error("Failed to sync time: %s", err)
                await self.disconnect()
                return False
        return True

    async def _send_ac_command(self, ac_num: int, subcommand: int, value: int) -> bool:
        """Send AC command message."""
        command = self._create_command(const.CMD_AC, ac_num, subcommand, value)
        return (await self._send_command(command)) is not None

    def _create_command(self, cmd: int, p1: int = 0, p2: int = 0, p3: int = 0) -> bytes:
        """Create 13-byte command message."""
        message = bytearray(
            [
                const.MSG_HEADER,
                cmd,
                const.MSG_LENGTH,
                p1 & 0xFF,
                p2 & 0xFF,
                p3 & 0xFF,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        )
        checksum = sum(message) & 0xFF
        message.append(checksum)
        return bytes(message)

    def _create_time_sync_command(self, when: datetime) -> bytes:
        """Build a 0x8B time synchronisation command."""
        year = when.year % 100
        month = min(11, max(0, when.month - 1))
        day = min(30, max(0, when.day - 1))
        hour = min(23, max(0, when.hour))
        minute = min(58, max(0, when.minute - 1))

        message = bytearray(
            [
                const.MSG_HEADER,
                const.CMD_TIME_SYNC,
                const.MSG_LENGTH,
                year,
                month,
                day,
                hour,
                minute,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        )
        checksum = sum(message) & 0xFF
        message.append(checksum)
        return bytes(message)

    async def _send_command(self, command: bytes) -> Optional[SystemState]:
        """Send a command and return parsed state."""
        if not self.connected:
            if not await self.connect():
                return None
        async with self._lock:
            assert self.writer and self.reader
            try:
                self.writer.write(command)
                await self.writer.drain()
            except Exception as err:  # noqa: BLE001
                LOGGER.error("Failed to send command: %s", err)
                await self.disconnect()
                return None

            state = await self._wait_for_state()
            if state:
                self._latest_state = state
            return state

    async def _wait_for_state(self) -> Optional[SystemState]:
        """Read from socket until a full state frame is parsed."""
        if not self.reader:
            return None
        while True:
            try:
                data = await asyncio.wait_for(
                    self.reader.read(1024),
                    timeout=const.READ_TIMEOUT,
                )
            except asyncio.TimeoutError:
                continue
            except Exception as err:  # noqa: BLE001
                LOGGER.error("Socket read failed: %s", err)
                await self.disconnect()
                return None

            if not data:
                LOGGER.debug("Connection closed by remote")
                await self.disconnect()
                return None

            messages = self._buffer.add_data(data)
            for msg in messages:
                if len(msg) != const.STATE_MSG_SIZE:
                    continue
                try:
                    return self._parse_state(msg)
                except Exception as err:  # noqa: BLE001
                    LOGGER.exception("Failed to parse state: %s", err)
                    return None

    def _parse_state(self, data: bytes) -> SystemState:
        """Parse 492-byte state message into a SystemState."""
        # LOGGER.debug("Parsing state message (%d bytes)", len(data))
        device_id = "".join(str(data[i] & 0x0F) for i in range(const.OFFSET_DEVICE_ID, const.OFFSET_DEVICE_ID + 8))
        system_name = bytes(
            data[const.OFFSET_SYSTEM_NAME : const.OFFSET_SYSTEM_NAME + const.STATE_SYSTEM_NAME_LENGTH]
        ).decode("ascii", errors="ignore").strip()
        zone_count = data[352]
        is_dual_ducted = bool(data[353] & 0x01)

        ac_units: list[AcState] = []
        for ac_num in range(2):
            status = data[const.OFFSET_AC_STATUS + ac_num]
            # App uses bit 7 for power (substring(0,1) on binary string with MSB first)
            # Bit 1 is error flag
            power_on = bool(status & 0x80)
            has_error = bool(status & 0x02)
            # if LOGGER.isEnabledFor(logging.DEBUG):
            #     LOGGER.debug(
            #         "AC %d: status_byte=0x%02x (%s), power_on=%s (bit7), has_error=%s (bit1)",
            #         ac_num + 1, status, format(status, '08b'), power_on, has_error
            #     )

            brand_id = data[const.OFFSET_AC_BRAND + ac_num]
            unit_id = data[const.OFFSET_AC_UNIT_ID + ac_num]
            if brand_id == 0 and unit_id in GATEWAY_BRAND_MAP:
                brand_id = GATEWAY_BRAND_MAP[unit_id]

            mode_raw = data[const.OFFSET_AC_MODE + ac_num] & 0x7F
            mode = self._decode_mode(mode_raw, brand_id)

            fan_byte = data[const.OFFSET_AC_FAN + ac_num]
            supported_bitmap = (fan_byte >> 4) & 0x0F
            fan_speed_value = fan_byte & 0x0F
            fan_speed = self._decode_fan_speed(fan_speed_value, brand_id, supported_bitmap)
            supported_fans = self._decode_supported_fans(supported_bitmap)

            setpoint = data[const.OFFSET_AC_SETPOINT + ac_num] & 0x7F
            room_temp_raw = data[const.OFFSET_AC_ROOM_TEMP + ac_num]
            room_temp = room_temp_raw - 256 if room_temp_raw > 127 else room_temp_raw

            error_low = data[const.OFFSET_AC_ERROR + (ac_num * 2)]
            error_high = data[const.OFFSET_AC_ERROR + (ac_num * 2) + 1]
            error_code = error_low + (error_high << 8)
            if brand_id == const.BRAND_REMAP_11 and 109 <= error_code <= 116:
                error_code = 0

            name_start = const.OFFSET_AC_NAMES + (ac_num * const.STATE_AC_NAME_LENGTH)
            name = bytes(
                data[name_start : name_start + const.STATE_AC_NAME_LENGTH]
            ).decode("ascii", errors="ignore").strip()

            control_mode = self._derive_control_mode(unit_id, brand_id)

            ac_units.append(
                AcState(
                    ac_number=ac_num,
                    name=name or f"AC {ac_num + 1}",
                    power_on=power_on,
                    mode=mode,
                    fan_speed=fan_speed,
                    setpoint=setpoint,
                    room_temp=room_temp,
                    brand_id=brand_id,
                    has_error=has_error,
                    error_code=error_code,
                    supported_fan_speeds=supported_fans,
                    control_mode=control_mode,
                )
            )

        # Parse touchpad assignments first (needed to determine has_sensor for zones)
        # Touchpad zone assignment: value is 1-indexed zone number, 0 means unassigned
        touchpad1_zone = data[const.OFFSET_TOUCHPAD_ZONE] - 1  # Convert to 0-indexed, -1 if unassigned
        touchpad2_zone = data[const.OFFSET_TOUCHPAD_ZONE + 1] - 1

        zones: list[ZoneState] = []
        for zone_num in range(zone_count):
            name_start = const.OFFSET_ZONE_NAMES + (zone_num * const.STATE_ZONE_NAME_LENGTH)
            name = bytes(
                data[name_start : name_start + const.STATE_ZONE_NAME_LENGTH]
            ).decode("ascii", errors="ignore").strip()

            group_byte = data[const.OFFSET_GROUP_DATA + zone_num]
            data_index = (group_byte >> 4) & 0x0F
            if not (0 <= data_index < const.STATE_ZONE_MAX):
                data_index = zone_num

            zone_data = data[const.OFFSET_ZONE_DATA + data_index]
            damper_byte = data[const.OFFSET_ZONE_DAMPER + data_index]
            damper_value = damper_byte & 0x7F
            damper_percent = min(100, damper_value * 5)

            # IMPORTANT: Temperature control mode (bit 7) is indexed by zone_num, NOT data_index.
            # The damper percentage (bits 0-6) uses data_index, but the control mode flag
            # is stored sequentially by zone number. This was verified via Wireshark captures
            # comparing the Android app's state reads against our parsing.
            temp_control_byte = data[const.OFFSET_ZONE_DAMPER + zone_num]
            temperature_control = bool(temp_control_byte & 0x80)

            # Zone data bits (MSB-first as per Android app's toFullBinaryString):
            # - Bit 7 (0x80): Zone ON/OFF state (1=ON, 0=OFF)
            # - Bit 6 (0x40): Spill mode indicator
            # - Bits 5-3: Program number
            # The Android app uses bit 7 for ON/OFF determination (see WifiCommService.java)
            is_on = bool(zone_data & 0x80)
            is_spill = bool(zone_data & 0x40)
            active_program = (zone_data >> 2) & 0x07

            # IMPORTANT: Feedback/setpoint is indexed by zone_num, NOT data_index.
            # This was verified by testing - data_index gives wrong setpoint values
            # for zones where data_index != zone_num.
            feedback = data[const.OFFSET_ZONE_FEEDBACK + zone_num]
            sensor_source = (feedback >> 5) & 0x07
            # Setpoint is bits 0-4 + 1 (stored as value - 1)
            # Testing: 28°C shows as raw 27 in bits 0-4, so we add 1
            setpoint_raw = feedback & 0x1F
            setpoint = (setpoint_raw + 1) if sensor_source > 0 else None

            # Zone has temperature capability if ANY of these are true:
            # 1. Touchpad 1 or 2 is assigned to this zone
            # 2. Wireless sensor slot (zone_num * 2) is available
            # 3. Wireless sensor slot (zone_num * 2 + 1) is available
            # This matches Android app's CalculateGroupTemp logic
            has_touchpad = (touchpad1_zone == zone_num) or (touchpad2_zone == zone_num)
            sensor1_slot = zone_num * 2
            sensor2_slot = zone_num * 2 + 1
            has_wireless_sensor1 = (
                sensor1_slot < const.STATE_SENSOR_SLOTS
                and bool(data[const.OFFSET_WIRELESS_SENSORS + sensor1_slot] & 0x80)
            )
            has_wireless_sensor2 = (
                sensor2_slot < const.STATE_SENSOR_SLOTS
                and bool(data[const.OFFSET_WIRELESS_SENSORS + sensor2_slot] & 0x80)
            )
            has_sensor = has_touchpad or has_wireless_sensor1 or has_wireless_sensor2

            zones.append(
                ZoneState(
                    zone_number=zone_num,
                    data_index=data_index,
                    name=name or f"Zone {zone_num + 1}",
                    is_on=is_on,
                    is_spill=is_spill,
                    damper_percent=damper_percent,
                    active_program=active_program,
                    setpoint=setpoint,
                    sensor_source=sensor_source,
                    temperature_control=temperature_control,
                    has_sensor=has_sensor,
                )
            )
        touchpads: list[TouchpadState] = []
        for tp_index in range(const.STATE_TOUCHPAD_COUNT):
            zone_assign = data[const.OFFSET_TOUCHPAD_ZONE + tp_index]
            assigned_zone = zone_assign - 1 if zone_assign > 0 else -1
            temp_raw = data[const.OFFSET_TOUCHPAD_TEMP + tp_index]
            # Temperature is in bits 0-6 (mask 0x7F)
            temp_value = temp_raw & 0x7F
            touchpads.append(
                TouchpadState(
                    touchpad_number=tp_index + 1,
                    assigned_zone=assigned_zone,
                    temperature=temp_value if temp_value > 0 else None,
                )
            )

        sensors: list[SensorState] = []
        for sensor_index in range(const.STATE_SENSOR_SLOTS):
            raw = data[const.OFFSET_WIRELESS_SENSORS + sensor_index]
            # Bit 7 = available, bit 6 = low battery, bits 0-5 = temperature
            available = bool(raw & 0x80)
            low_battery = bool(raw & 0x40)
            temperature = raw & 0x3F
            sensors.append(
                SensorState(
                    sensor_number=sensor_index + 1,
                    available=available,
                    low_battery=low_battery,
                    temperature=temperature,
                )
            )

        return SystemState(
            raw_data=data,
            device_id=device_id,
            system_name=system_name or "AirTouch 3",
            zone_count=zone_count,
            is_dual_ducted=is_dual_ducted,
            ac_units=ac_units,
            zones=zones,
            sensors=sensors,
            touchpads=touchpads,
        )

    def _encode_mode(self, mode: AcMode, brand: int) -> int:
        """Encode AC mode for a command."""
        value = int(mode)
        if brand == const.BRAND_REMAP_11:
            remap = {0: 0, 1: 2, 2: 3, 3: 4, 4: 1}
            return remap.get(value, value)
        if brand == const.BRAND_REMAP_15:
            remap = {0: 5, 1: 2, 2: 3, 3: 4, 4: 1}
            return remap.get(value, value)
        return value

    def _decode_mode(self, value: int, brand: int) -> AcMode:
        """Decode mode from state, reversing brand remaps."""
        if brand in (const.BRAND_REMAP_11, const.BRAND_REMAP_15):
            decode = {0: 0, 1: 4, 2: 1, 3: 2, 4: 3, 5: 0}
            value = decode.get(value, value)
        try:
            return AcMode(value)
        except ValueError:
            return AcMode.AUTO

    def _decode_supported_fans(self, supported: int) -> List[FanSpeed]:
        """Return list of supported fan speeds."""
        if supported >= 4:
            modes: Iterable[FanSpeed] = (
                FanSpeed.AUTO,
                FanSpeed.QUIET,
                FanSpeed.LOW,
                FanSpeed.MEDIUM,
                FanSpeed.HIGH,
                FanSpeed.POWERFUL,
            )
        elif supported == 3:
            modes = (FanSpeed.AUTO, FanSpeed.LOW, FanSpeed.MEDIUM, FanSpeed.HIGH)
        elif supported == 2:
            modes = (FanSpeed.AUTO, FanSpeed.LOW, FanSpeed.HIGH)
        else:
            modes = (FanSpeed.AUTO, FanSpeed.LOW, FanSpeed.MEDIUM, FanSpeed.HIGH)
        return list(modes)

    def _decode_fan_speed(self, value: int, brand: int, supported: int) -> FanSpeed:
        """Decode fan speed from state value.

        Based on app's ACInfo.formatFanSpeed():
        - 0 = Auto, 1 = Low, 2 = Medium, 3 = High, 4 = Powerful
        - Brand 15: value 4 = Auto
        - Brand 2 with supported=4: use value-1 as index
        """
        if brand == const.BRAND_REMAP_15 and value == 4:
            return FanSpeed.AUTO
        if value == 0 or value >= 5:
            return FanSpeed.AUTO

        if brand == const.BRAND_SPECIAL_FAN and supported >= 4:
            value = max(1, value - 1)

        mapping = {
            1: FanSpeed.LOW,
            2: FanSpeed.MEDIUM,
            3: FanSpeed.HIGH,
            4: FanSpeed.POWERFUL,
        }
        return mapping.get(value, FanSpeed.AUTO)

    def _encode_fan_speed(self, speed: FanSpeed, brand: int, supported: int) -> int:
        """Encode fan speed command value.

        Based on app's ACInfo.formatFanSpeed():
        - Low = 1, Medium = 2, High = 3, Powerful = 4
        - Brand 15: Auto = 4, otherwise Auto = 0
        - Brand 2 with supported=4: add 1 to value
        """
        if speed == FanSpeed.AUTO:
            return 4 if brand == const.BRAND_REMAP_15 else 0

        value_map = {
            FanSpeed.QUIET: 1,  # Treated same as Low for brands without Quiet
            FanSpeed.LOW: 1,
            FanSpeed.MEDIUM: 2,
            FanSpeed.HIGH: 3,
            FanSpeed.POWERFUL: 4,
        }
        value = value_map.get(speed, 0)
        if brand == const.BRAND_SPECIAL_FAN and supported >= 4:
            value += 1
        return value

    def _derive_control_mode(self, unit_id: int, brand_id: int) -> int:
        """Determine control mode level from IDs."""
        if unit_id == 0 and brand_id == 0:
            return 0
        if unit_id == 0:
            return 1
        return 2

    def _get_brand(self, ac_num: int) -> int:
        """Get brand for AC number from latest state."""
        if self._latest_state and len(self._latest_state.ac_units) > ac_num:
            return self._latest_state.ac_units[ac_num].brand_id
        return 0

    def _get_supported_fan_bitmap(self, ac_num: int) -> int:
        """Get supported fan bitmap from latest state fan byte."""
        if not self._latest_state or len(self._latest_state.ac_units) <= ac_num:
            return 0
        # Re-encode to bitmap length from supported list
        supported = self._latest_state.ac_units[ac_num].supported_fan_speeds
        if FanSpeed.POWERFUL in supported:
            return 4
        if FanSpeed.MEDIUM in supported and FanSpeed.HIGH in supported:
            return 3
        if FanSpeed.HIGH in supported:
            return 2
        return 0
