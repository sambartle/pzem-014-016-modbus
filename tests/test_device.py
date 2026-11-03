"""How the meter is polled: one request, and what a failure does."""

from __future__ import annotations

import pytest
from modbus_connection import (
    IllegalDataAddressError,
    ModbusConnectionError,
    ModbusTimeoutError,
)
from modbus_connection.mock import MockModbusUnit, ReadEvent

from pzem_014_016_modbus import PzemMeter


async def test_a_poll_is_a_single_request(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit
) -> None:
    report = await meter.async_update_readings()
    assert report.complete
    assert report.updated == {"measurements"}
    assert mock_modbus_unit.read_events == [ReadEvent("input", 0, 10)]


async def test_settings_are_polled_apart_from_the_readings(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit
) -> None:
    report = await meter.async_update_settings()
    assert report.updated == {"settings"}
    assert mock_modbus_unit.read_events == [ReadEvent("holding", 1, 2)]
    assert meter.measurements.voltage is None


async def test_a_full_update_reports_both(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit
) -> None:
    report = await meter.async_update()
    assert report.updated == {"measurements", "settings"}
    assert len(mock_modbus_unit.read_events) == 2


async def test_listeners_fire_once_per_poll(meter: PzemMeter) -> None:
    seen: list[float | None] = []
    meter.measurements.add_update_listener(
        lambda: seen.append(meter.measurements.voltage)
    )
    await meter.async_update()
    await meter.async_update()
    assert seen == [230.1, 230.1]


async def test_a_refused_block_keeps_the_previous_values(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit
) -> None:
    await meter.async_update()
    mock_modbus_unit.input[0] = 2400
    mock_modbus_unit.fail_read(0, IllegalDataAddressError(0), register_type="input")
    seen: list[int] = []
    meter.measurements.add_update_listener(lambda: seen.append(1))

    report = await meter.async_update()

    assert not report.complete
    assert set(report.failed) == {"measurements"}
    assert meter.measurements.voltage == pytest.approx(230.1)
    assert seen == []


async def test_a_silent_meter_raises(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit
) -> None:
    mock_modbus_unit.fail_requests(ModbusTimeoutError("asleep"))
    with pytest.raises(ModbusTimeoutError):
        await meter.async_update()


async def test_a_dead_link_raises(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit
) -> None:
    mock_modbus_unit.fail_requests(ModbusConnectionError("gone"))
    with pytest.raises(ModbusConnectionError):
        await meter.async_update()


async def test_a_meter_recovers_after_a_silent_poll(
    meter: PzemMeter, mock_modbus_unit: MockModbusUnit
) -> None:
    mock_modbus_unit.fail_requests(ModbusTimeoutError("asleep"))
    with pytest.raises(ModbusTimeoutError):
        await meter.async_update()
    mock_modbus_unit.fail_requests(None)
    await meter.async_update()
    assert meter.measurements.voltage == pytest.approx(230.1)


async def test_the_timeout_is_asked_of_the_link(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    PzemMeter(mock_modbus_unit)
    assert mock_modbus_unit.required_timeout is None
    PzemMeter(mock_modbus_unit, timeout=3)
    assert mock_modbus_unit.required_timeout == 3


async def test_connected_follows_the_link(
    meter: PzemMeter,
) -> None:
    assert not meter.connected
    await meter.async_update()
    assert meter.connected


async def test_read_raw_is_undecoded_and_does_not_notify(
    meter: PzemMeter,
) -> None:
    seen: list[int] = []
    meter.measurements.add_update_listener(lambda: seen.append(1))
    raw = await meter.async_read_raw()
    assert raw == {
        "holding": {1: 2300, 2: 1},
        "input": {
            0: 2301,
            1: 12345,
            2: 0,
            3: 12345,
            4: 0,
            5: 4464,
            6: 1,
            7: 500,
            8: 98,
            9: 0,
        },
    }
    assert seen == []
