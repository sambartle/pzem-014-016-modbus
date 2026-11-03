"""The register map, decoded over the mock backend."""

from __future__ import annotations

import pytest
from modbus_connection.mock import MockModbusUnit
from modbus_connection.model import RegisterField

from pzem_014_016_modbus import Measurements, PzemMeter


async def test_every_field_decodes(meter: PzemMeter) -> None:
    await meter.async_update()
    measurements = meter.measurements
    assert measurements.voltage == pytest.approx(230.1)
    assert measurements.current == pytest.approx(12.345)
    assert measurements.power == pytest.approx(1234.5)
    assert measurements.energy == 70000
    assert measurements.frequency == pytest.approx(50.0)
    assert measurements.power_factor == pytest.approx(0.98)
    assert measurements.power_alarm is False


async def test_nothing_is_read_before_the_first_poll(meter: PzemMeter) -> None:
    assert meter.measurements.voltage is None
    assert meter.measurements.energy is None


async def test_32_bit_values_send_their_low_word_first(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    # 0x0001_0000 + 5: the high word is 1, the low word 5.
    mock_modbus_unit.input[1] = [5, 1]
    mock_modbus_unit.input[5] = [5, 1]
    measurements = Measurements(mock_modbus_unit)
    await measurements.async_update()
    assert measurements.current == pytest.approx(65.541)
    assert measurements.energy == 65541


async def test_values_are_unsigned(mock_modbus_unit: MockModbusUnit) -> None:
    mock_modbus_unit.input[0] = 0xFFFF
    mock_modbus_unit.input[3] = [0xFFFF, 0xFFFF]
    measurements = Measurements(mock_modbus_unit)
    await measurements.async_update()
    assert measurements.voltage == pytest.approx(6553.5)
    assert measurements.power == pytest.approx(429496729.5)


@pytest.mark.parametrize(
    ("register", "alarm"),
    [(0x0000, False), (0xFFFF, True), (0x0001, None)],
)
async def test_alarm_status(
    mock_modbus_unit: MockModbusUnit, register: int, alarm: bool | None
) -> None:
    """The meter sets every bit for an alarm; anything else is unknown."""
    mock_modbus_unit.input[9] = register
    measurements = Measurements(mock_modbus_unit)
    await measurements.async_update()
    assert measurements.power_alarm is alarm


async def test_units_are_declared_on_the_fields() -> None:
    units = {
        name: field.unit
        for name, field in Measurements.declared_fields.items()
        if isinstance(field, RegisterField)
    }
    assert units == {
        "voltage": "V",
        "current": "A",
        "power": "W",
        "energy": "Wh",
        "frequency": "Hz",
        "power_factor": None,
        "power_alarm": None,
    }


async def test_the_fields_read_from_the_input_registers(
    mock_modbus_unit: MockModbusUnit,
) -> None:
    """A holding register at the same address must not be mistaken for them."""
    mock_modbus_unit.holding[0] = 9999
    mock_modbus_unit.input[0] = 2301
    measurements = Measurements(mock_modbus_unit)
    await measurements.async_update()
    assert measurements.voltage == pytest.approx(230.1)
