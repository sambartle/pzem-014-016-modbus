"""Fixtures: a meter on modbus-connection's in-memory mock backend."""

from __future__ import annotations

import pytest
from modbus_connection.mock import MockModbusUnit

from pzem_014_016_modbus import PzemMeter

# A live reading: 230.1 V, 12.345 A, 1234.5 W, 70000 Wh, 50.0 Hz, power factor 0.98,
# no alarm.
# The 32-bit values send their low word first.
METER_INPUT: dict[int, int | list[int]] = {
    0: 2301,  # voltage -> 230.1 V
    1: [12345, 0],  # current -> 12.345 A
    3: [12345, 0],  # power -> 1234.5 W
    5: [70000 & 0xFFFF, 70000 >> 16],  # energy -> 70000 Wh
    7: 500,  # frequency -> 50.0 Hz
    8: 98,  # power factor -> 0.98
    9: 0,  # alarm status -> no alarm
}

# Configured to alarm at 2300 W, answering to address 1.
METER_HOLDING: dict[int, int | list[int]] = {1: 2300, 2: 1}


@pytest.fixture
def meter(mock_modbus_unit: MockModbusUnit) -> PzemMeter:
    """A meter answering the readings above."""
    mock_modbus_unit.input.update(METER_INPUT)
    mock_modbus_unit.holding.update(METER_HOLDING)
    return PzemMeter(mock_modbus_unit)
