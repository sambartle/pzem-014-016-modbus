# pzem-014-016-modbus

Read PZEM-014 and PZEM-016 Modbus AC energy meters (and register-compatible
meters such as the PZEM-004T v3),
as typed Python objects rather than register numbers.

The library maps the meter's register set onto
[modbus-connection](https://github.com/home-assistant-libs/modbus-connection)'s device model:
you hand it a `ModbusUnit`, call `async_update()`, and read the measurements as
attributes. It owns no connection and no I/O policy — the caller does.

## Supported devices

The meter publishes ten input registers (function code 4) and two holding
registers (function codes 3 and 6). This library reads all of them.

Measurements, in the `Measurements` component:

| Register | Field | Type | Scale | Unit |
| :--- | :--- | :--- | :--- | :--- |
| 0 | `voltage` | 16-bit | 0.1 | V |
| 1–2 | `current` | 32-bit, low word first | 0.001 | A |
| 3–4 | `power` | 32-bit, low word first | 0.1 | W |
| 5–6 | `energy` | 32-bit, low word first | 1 | Wh |
| 7 | `frequency` | 16-bit | 0.1 | Hz |
| 8 | `power_factor` | 16-bit | 0.01 | — |
| 9 | `power_alarm` | `bool`: 0xFFFF alarm, 0x0000 none | | |

Settings, in the `Settings` component, which are writable:

| Register | Field | Range | Unit |
| :--- | :--- | :--- | :--- |
| 1 | `power_alarm_threshold` | 0 to 65535 | W |
| 2 | `modbus_address` | 1 to 247 | |

All values are unsigned. A meter with this register map, at the usual 9600
baud, 8 data bits, no parity and 1 stop bit over RS-485, works. This was
written against the PZEM-014 (10 A, built-in shunt) and PZEM-016 (100 A,
external current transformer) datasheet; the two share one register map.

`PzemMeter` is the top-level device that holds both components. A poll of the
measurements is a single request for registers 0 to 9, and the settings are a
second request for the two holding registers.

Not supported: the meter's reset-energy command (function code 0x42) and its
factory calibration (0x41). `ModbusUnit` carries the standard function codes
only, so a custom one cannot be sent through it. Reset the energy counter with
the manufacturer's software.

## Usage

```python
import asyncio

from modbus_connection import ModbusSerialParams
from modbus_connection.tmodbus import ModbusConnection
from pzem_014_016_modbus import PzemMeter


async def main() -> None:
    connection = ModbusConnection(ModbusSerialParams(device="/dev/ttyUSB0"))
    try:
        meter = PzemMeter(connection.for_unit(1))
        await meter.async_update()

        print("Voltage:", meter.measurements.voltage, "V")
        print("Current:", meter.measurements.current, "A")
        print("Power:", meter.measurements.power, "W")
        print("Energy:", meter.measurements.energy, "Wh")
        print("Frequency:", meter.measurements.frequency, "Hz")
        print("Power factor:", meter.measurements.power_factor)
    finally:
        await connection.close()


asyncio.run(main())
```

A value is `None` until the first poll has read it. `async_update()` refreshes
the measurements and the settings in one merged report. A poll of the two apart
is also available: `async_update_readings()` for what the meter measures, every
few seconds, and `async_update_settings()` for what it has been configured to do,
which only changes when something writes it. Each returns an `UpdateReport`: a component that failed keeps its previous values, does not
notify its listeners, and is listed by attribute name with its error. A dead
link (`ModbusConnectionError`) raises, and so does a timeout while nothing has
answered yet, since a meter that is simply not responding has nothing to report.

```python
report = await meter.async_update()
for name, error in report.failed.items():
    print(f"{name} kept its previous values: {error}")
```

To react to a refresh, register a listener on the component. It fires once the
poll is done, and only for a component that refreshed:

```python
meter.measurements.add_update_listener(lambda: print(meter.measurements.power))
```

### Changing the settings

A typed method per setting writes it with function code 6, the only write the
meter takes. Run a settings poll afterwards to read back what took effect:

```python
await meter.settings.async_write_power_alarm_threshold(2300)  # watts
await meter.async_update_settings()
print(meter.settings.power_alarm_threshold, meter.measurements.power_alarm)
```

A value outside the register's range raises `ValueError` before anything is
sent. Writing the Modbus address moves the meter: it answers on the new address
and no longer on the old one, so build a new unit to keep talking to it.

```python
await meter.settings.async_write_modbus_address(5)
meter = PzemMeter(connection.for_unit(5))
```

An address another device on the bus already uses cannot be detected from here.

`async_read_raw()` dumps every register the meter reads, undecoded, keyed by
address space and address. It fires no update listeners — a download is not a
poll. It is what an issue about a wrong value should quote.

## Checking a real meter

`script/query.py` reads one meter once and prints every value it serves, which
is the quickest way to see whether a meter is reachable and addressed
correctly:

```bash
# a USB or serial adapter
uv run script/query.py /dev/ttyUSB0 --transport serial --unit 1
# a box forwarding the RTU frames over TCP
uv run script/query.py socket://192.168.1.50:8899 --transport serial --unit 1
# a gateway answering Modbus TCP: pass no framing (502 is the default)
uv run script/query.py 192.168.1.50 --port 502 --unit 1
# every register read, plus ranges the library does not model
uv run script/query.py /dev/ttyUSB0 --transport serial --raw --registers 0x0000:10
# alarm above 2300 W (writes the meter's alarm threshold register)
uv run script/query.py /dev/ttyUSB0 --transport serial --set-alarm-threshold 2300
# move the meter to address 5 (writes its Modbus address register)
uv run script/query.py /dev/ttyUSB0 --transport serial --unit 1 --set-address 5
```

Which line fits depends on what sits between you and the meter's RS-485 line,
as [Naming the link](#naming-the-link) explains. With a gateway answering
Modbus TCP, leave the framing out: an RTU framing there times out on every
register, which looks exactly like a meter that is switched off.

`--registers ADDR[:COUNT]` reads any input range raw, up to 125 registers per
range, for checking a register the library does not model yet. The script only
reads, except for the two options that write a setting:
`--set-alarm-threshold WATTS` and `--set-address ADDRESS`. The second moves the
meter, which is how to give each meter on a shared bus its own address one at a
time.

## Naming the link

A meter answers RTU on its RS-485 line, so how to name the link depends on what
sits between you and that line, not on the meter:

| Between you and the line | Parameters |
| :--- | :--- |
| Nothing: a USB or serial adapter | `ModbusSerialParams(device="/dev/ttyUSB0")` |
| A box forwarding the RTU frames | `ModbusSerialParams(device="socket://host:port")` |
| A gateway answering Modbus TCP | `ModbusTcpParams(host=...)` |

The second one is what `ModbusTcpParams(framer="rtu")` used to spell, which
modbus-connection 4.12 deprecates: those frames are a serial line however they
reach you, so a consumer pooling connections by endpoint opened two links onto
one half-duplex bus when two callers spelled it differently.

ASCII framing is unsupported. This library never accepts or forwards it, and it
exposes no connect helper that could, since the caller builds the `ModbusUnit`
and hands it over.

## How long a request waits

The timeout is spent per request, so it is what a poll loses when the meter
does not answer. The meter itself is quick, but what sits between it and you
varies far more, so the device object does not guess a value: the connection's
own default applies.

A caller who has measured their link states it with `timeout=` on the
constructor, which asks for it through `ModbusUnit.require_timeout()`:

```python
meter = PzemMeter(connection.for_unit(1), timeout=3)
```

Two things to know before setting one: the connection runs with the largest
value any of its units asks for, so a device sharing the link can raise it, and
a lowered value takes effect at the next connect rather than on the link already
open.

## Testing without a meter

modbus-connection ships an in-memory backend and a pytest plugin, so the
library's own tests need no hardware:

```python
from modbus_connection.mock import MockModbusUnit

from pzem_014_016_modbus import PzemMeter


async def test_voltage(mock_modbus_unit: MockModbusUnit) -> None:
    mock_modbus_unit.input[0] = 2301
    meter = PzemMeter(mock_modbus_unit)
    await meter.async_update()
    assert meter.measurements.voltage == 230.1
```

## Development

```bash
uv sync
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Releases are described in [RELEASING.md](RELEASING.md).

## Attribution

The register map is taken from a Modbus register configuration of a PZEM-014/016
meter, and checked against the manufacturer's PZEM-014/016 communication module
datasheet. This library keeps that configuration's addresses, scale factors,
units and word order, and is released under the Apache-2.0 licence.
