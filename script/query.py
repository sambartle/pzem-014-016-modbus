#!/usr/bin/env python3

"""Query a PZEM-014/016 meter and print every value."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from modbus_connection import ModbusError
from modbus_connection.cli_helper import (
    add_connection_args,
    connect_from_args,
    print_component,
)

from pzem_014_016_modbus import PzemMeter

# The meter's RS-485 line, direct or through a socket:// device, and the
# gateways answering Modbus TCP themselves. No ASCII: the library does not
# support it.
CONNECTIONS = (("tcp", "socket"), ("serial", "rtu"))

# The most registers one Modbus read may ask for.
MAX_COUNT = 125

EXAMPLES = """examples:
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
"""

RegisterRead = tuple[int, int, list[int] | str]


def _register_range(text: str) -> tuple[int, int]:
    """Parse ``ADDR[:COUNT]``, each decimal or 0x-prefixed."""
    address, _, count = text.partition(":")
    try:
        start, length = int(address, 0), int(count or "1", 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not ADDR[:COUNT]") from None
    if not 1 <= length <= MAX_COUNT or not 0 <= start <= 0x10000 - length:
        raise argparse.ArgumentTypeError(
            f"{text!r} must read 1 to {MAX_COUNT} registers ending by 0xFFFF"
        )
    return start, length


async def main() -> int:
    """Read one meter and print it.

    Without the ``--set-*`` options this only reads.
    """
    # The backend logs a failed connect at ERROR with its traceback; the
    # messages below say it in one line.
    logging.getLogger().addHandler(logging.NullHandler())

    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_connection_args(parser, connections=CONNECTIONS)
    parser.add_argument("--unit", type=int, default=1, help="Modbus unit id")
    parser.add_argument(
        "--raw", action="store_true", help="also dump every register read, as JSON"
    )
    parser.add_argument(
        "--registers",
        type=_register_range,
        action="append",
        default=[],
        metavar="ADDR[:COUNT]",
        help=f"also read these input registers, up to {MAX_COUNT} at a time",
    )
    parser.add_argument(
        "--set-alarm-threshold",
        type=int,
        metavar="WATTS",
        help="first write the power alarm threshold (0x0001), in watts",
    )
    parser.add_argument(
        "--set-address",
        type=int,
        metavar="ADDRESS",
        help="first write the meter's Modbus address (0x0002), 1 to 247; "
        "the meter then answers on the new address only",
    )
    args = parser.parse_args()

    try:
        connection = await connect_from_args(args)
    except ModbusError as err:
        # A connect timeout arrives with no message of its own.
        detail = str(err) or type(err).__name__
        print(f"Could not connect to {args.target}: {detail}")
        return 1

    unit = connection.for_unit(args.unit)
    meter = PzemMeter(unit)
    reads: list[RegisterRead] = []
    try:
        if args.set_alarm_threshold is not None:
            await meter.settings.async_write_power_alarm_threshold(
                args.set_alarm_threshold
            )
            print(f"Alarm threshold set to {args.set_alarm_threshold} W")
        if args.set_address is not None:
            await meter.settings.async_write_modbus_address(args.set_address)
            print(f"Modbus address set to {args.set_address}")
            # The meter has moved: read it where it answers now.
            unit = connection.for_unit(args.set_address)
            meter = PzemMeter(unit)
        report = await meter.async_update()
        for start, count in args.registers:
            try:
                values: list[int] | str = await unit.read_input_registers(start, count)
            except ModbusError as err:
                values = str(err) or type(err).__name__
            reads.append((start, count, values))
        raw = await meter.async_read_raw() if args.raw else None
    except (ModbusError, ValueError) as err:
        print(f"Could not read the meter: {str(err) or type(err).__name__}")
        return 1
    finally:
        await connection.close()

    print_component(meter.measurements, title="measurements")
    print()
    print_component(meter.settings, title="settings")
    if report.failed:
        print("\nFailed to read:")
        for name, error in report.failed.items():
            print(f"  {name}: {str(error) or type(error).__name__}")
    for start, count, values in reads:
        print(f"\nInput registers 0x{start:04X}-0x{start + count - 1:04X}")
        if isinstance(values, str):
            print(f"  {values}")
            continue
        for offset, value in enumerate(values):
            print(f"  0x{start + offset:04X}  0x{value:04X}  {value}")
    if raw is not None:
        print("\nRaw registers")
        # The dump arrives address-ordered; sorting keys would undo that.
        print(json.dumps(raw, indent=2))
    return 0


raise SystemExit(asyncio.run(main()))
