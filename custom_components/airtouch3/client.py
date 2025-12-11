"""Async TCP client for the AirTouch 3 protocol."""

from __future__ import annotations

import asyncio
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
        device_id = "".join(str(data[i] & 0x0F) for i in range(const.OFFSET_DEVICE_ID, const.OFFSET_DEVICE_ID + 8))
        system_name = bytes(
            data[const.OFFSET_SYSTEM_NAME : const.OFFSET_SYSTEM_NAME + const.STATE_SYSTEM_NAME_LENGTH]
        ).decode("ascii", errors="ignore").strip()
        zone_count = data[352]
        is_dual_ducted = bool(data[353] & 0x01)

        ac_units: list[AcState] = []
        for ac_num in range(2):
            status = data[const.OFFSET_AC_STATUS + ac_num]
            power_on = bool(status & 0x01)
            has_error = bool(status & 0x02)

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
            damper_value = data[const.OFFSET_ZONE_DAMPER + data_index] & 0x7F
            damper_percent = min(100, damper_value * 5)

            # Zone data (per protocol): bit0 on/off, bit1 spill, bits2-4 program.
            low_on = bool(zone_data & 0x01)
            low_spill = bool(zone_data & 0x02)
            high_on = bool(zone_data & 0x80)
            high_spill = bool(zone_data & 0x40)
            # Heuristic: treat zone as on if any flag says on OR damper is not fully open.
            is_on = high_on or low_on or damper_percent < 95
            is_spill = low_spill or high_spill
            active_program = (zone_data >> 2) & 0x07

            feedback = data[const.OFFSET_ZONE_FEEDBACK + data_index]
            sensor_source = (feedback >> 5) & 0x07
            setpoint = (feedback & 0x1F) + 1 if sensor_source > 0 else None

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
                )
            )
            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.debug(
                    "Zone %s (group %s -> data %s, group_byte=0x%02x, zone_data=0x%02x high_on=%s high_spill=%s): on=%s spill=%s damper_raw=%s (%s%%) feedback=0x%02x",
                    name or zone_num,
                    zone_num,
                    data_index,
                    group_byte,
                    zone_data,
                    high_on,
                    high_spill,
                    is_on,
                    is_spill,
                    damper_value,
                    damper_percent,
                    feedback,
                )

        touchpads: list[TouchpadState] = []
        for tp_index in range(const.STATE_TOUCHPAD_COUNT):
            zone_assign = data[const.OFFSET_TOUCHPAD_ZONE + tp_index]
            assigned_zone = zone_assign - 1 if zone_assign > 0 else -1
            temp_raw = data[const.OFFSET_TOUCHPAD_TEMP + tp_index]
            temp_value = (temp_raw >> 1) & 0x7F
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
            available = bool(raw & 0x01)
            low_battery = bool(raw & 0x02)
            temperature = (raw >> 2) & 0x3F
            sensors.append(
                SensorState(
                    sensor_number=sensor_index + 1,
                    available=available,
                    low_battery=low_battery,
                    temperature=temperature,
                )
            )

        if LOGGER.isEnabledFor(logging.DEBUG):
            zone_bytes = data[const.OFFSET_ZONE_DATA : const.OFFSET_ZONE_DATA + const.STATE_ZONE_MAX]
            group_bytes = data[const.OFFSET_GROUP_DATA : const.OFFSET_GROUP_DATA + const.STATE_ZONE_MAX]
            LOGGER.debug(
                "Zone data bytes: %s; Group data bytes: %s",
                " ".join(f"{b:02x}" for b in zone_bytes),
                " ".join(f"{b:02x}" for b in group_bytes),
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
        """Decode fan speed from state value."""
        if brand == const.BRAND_REMAP_15 and value == 4:
            return FanSpeed.AUTO
        if value == 0 or value >= 5:
            return FanSpeed.AUTO

        if brand == const.BRAND_SPECIAL_FAN and supported >= 4:
            value = max(1, value - 1)

        mapping = {
            1: FanSpeed.QUIET,
            2: FanSpeed.LOW,
            3: FanSpeed.MEDIUM,
            4: FanSpeed.HIGH,
        }
        return mapping.get(value, FanSpeed.AUTO)

    def _encode_fan_speed(self, speed: FanSpeed, brand: int, supported: int) -> int:
        """Encode fan speed command value."""
        if speed == FanSpeed.AUTO:
            return 4 if brand == const.BRAND_REMAP_15 else 0

        value_map = {
            FanSpeed.QUIET: 1,
            FanSpeed.LOW: 2,
            FanSpeed.MEDIUM: 3,
            FanSpeed.HIGH: 4,
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
