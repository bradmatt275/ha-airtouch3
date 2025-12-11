"""Typed data models for AirTouch 3 state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional


class AcMode(IntEnum):
    """AC operating modes."""

    AUTO = 0
    HEAT = 1
    DRY = 2
    FAN = 3
    COOL = 4


class FanSpeed(IntEnum):
    """Fan speed values."""

    AUTO = 0
    QUIET = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    POWERFUL = 5


@dataclass
class AcState:
    """State for a single AC unit."""

    ac_number: int
    name: str
    power_on: bool
    mode: AcMode
    fan_speed: FanSpeed
    setpoint: int
    room_temp: int
    brand_id: int
    has_error: bool
    error_code: int
    supported_fan_speeds: List[FanSpeed]
    control_mode: int


@dataclass
class ZoneState:
    """State for a single zone."""

    zone_number: int
    name: str
    is_on: bool
    is_spill: bool
    damper_percent: int
    active_program: int
    setpoint: Optional[int]
    sensor_source: int


@dataclass
class SensorState:
    """Wireless sensor state."""

    sensor_number: int
    available: bool
    low_battery: bool
    temperature: int


@dataclass
class TouchpadState:
    """Touchpad state."""

    touchpad_number: int
    assigned_zone: int
    temperature: Optional[int]


@dataclass
class SystemState:
    """Complete parsed system state."""

    raw_data: bytes
    device_id: str
    system_name: str
    zone_count: int
    is_dual_ducted: bool
    ac_units: List[AcState]
    zones: List[ZoneState]
    sensors: List[SensorState]
    touchpads: List[TouchpadState]

