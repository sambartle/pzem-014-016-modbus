"""The configurable registers: reading them, and writing them back."""

from __future__ import annotations

import pytest
from modbus_connection.mock import MockModbusUnit, WriteEvent

from pzem_014_016_modbus import MAX_ADDRESS, PzemMeter, Settings


async def test_settings_decode(meter: PzemMeter) -> None:
    await meter.async_update_settings()
    assert meter.settings.power_alarm_threshold == 2300
    assert meter.settings.modbus_address == 1


async def test_the_settings_read_from_the_holding_registers(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """The input register at the same address is a different register."""
    mock_modbus_unit.input[1] = 1
    mock_modbus_unit.holding[1] = 2300
    settings = Settings(mock_modbus_unit)
    await settings.async_update()
    assert settings.power_alarm_threshold == 2300


async def test_writing_the_alarm_threshold(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit
) -> None:
    writes: list[WriteEvent] = []
    mock_modbus_unit.on_write(writes.append)

    await meter.settings.async_write_power_alarm_threshold(1500)
    await meter.async_update_settings()

    # The meter only takes function code 6, a single register.
    assert writes == [WriteEvent("holding", 1, [1500], 6)]
    assert meter.settings.power_alarm_threshold == 1500


async def test_writing_the_modbus_address(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit
) -> None:
    writes: list[WriteEvent] = []
    mock_modbus_unit.on_write(writes.append)

    await meter.settings.async_write_modbus_address(5)

    assert writes == [WriteEvent("holding", 2, [5], 6)]


@pytest.mark.parametrize("watts", [-1, 65536])
async def test_an_alarm_threshold_outside_the_register_is_refused(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit, watts: int
) -> None:
    writes: list[WriteEvent] = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(ValueError, match="alarm threshold"):
        await meter.settings.async_write_power_alarm_threshold(watts)
    assert writes == []


@pytest.mark.parametrize("address", [0, MAX_ADDRESS + 1])
async def test_an_address_the_meter_does_not_accept_is_refused(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit, address: int
) -> None:
    """0 is the broadcast address and 0xF8 is for single-slave calibration."""
    writes: list[WriteEvent] = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(ValueError, match="Modbus address"):
        await meter.settings.async_write_modbus_address(address)
    assert writes == []
