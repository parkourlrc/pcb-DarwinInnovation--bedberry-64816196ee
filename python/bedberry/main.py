from __future__ import annotations

import argparse
import asyncio
import glob
import logging
import signal
from pathlib import Path

import RPi.GPIO as GPIO
from smbus2 import SMBus

from .config import (
    load_all_mcp23017_from_i2c_config,
    load_multibutton_config,
    load_okin_bed_config,
    load_okin_remote_config,
)
from .i2c_bus import WbI2cBus
from .mcp23017 import MCP23017
from .multibutton import MultiButton
from .okin_bed import OkinBed
from .okin_remote import OkinRemote


LOGGER = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bedberry core runtime")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(__file__).parent.parent / "cfg",
        help="Path to config directory",
    )
    parser.add_argument("--i2c-bus", type=int, default=1, help="Linux i2c bus number")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )
    return parser.parse_args()


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _list_i2c_buses() -> list[int]:
    buses: list[int] = []
    for path in glob.glob("/dev/i2c-*"):
        try:
            buses.append(int(path.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return sorted(set(buses))


def _bus_has_device(bus_id: int, address: int) -> bool:
    try:
        with SMBus(bus_id) as bus:
            bus.read_byte_data(address, 0x00)
        return True
    except OSError:
        return False


def _resolve_i2c_bus_for_device(requested: int, address: int) -> int:
    available = _list_i2c_buses()
    if not available:
        raise FileNotFoundError(
            "No /dev/i2c-* devices found. Enable I2C and check kernel/device-tree configuration."
        )

    if requested not in available:
        raise FileNotFoundError(
            f"Requested I2C bus {requested} does not exist"
        )

    if _bus_has_device(requested, address):
        return requested

    raise FileNotFoundError(
        f"Could not find I2C device 0x{address:02x} on requested bus {requested}"
    )


async def _run(args: argparse.Namespace) -> None:
    config_dir = args.config_dir.resolve()
    LOGGER.info("Starting Bedberry core (config=%s, requested_i2c_bus=%d)", config_dir, args.i2c_bus)

    mcp_cfgs = load_all_mcp23017_from_i2c_config(config_dir)
    bed_cfg = load_okin_bed_config(config_dir)
    remote_cfg = load_okin_remote_config(config_dir)
    mb_cfg = load_multibutton_config(config_dir)

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    # Resolve the bus using the primary (first) device address
    resolved_bus = _resolve_i2c_bus_for_device(args.i2c_bus, mcp_cfgs[0].address)
    LOGGER.info("Using I2C bus %d", resolved_bus)
    i2c_bus = WbI2cBus(resolved_bus)
    loop = asyncio.get_running_loop()

    mcps: dict[str, MCP23017] = {}
    for mcp_cfg in mcp_cfgs:
        LOGGER.info("Initialising MCP23017 name=%s address=0x%02x", mcp_cfg.name, mcp_cfg.address)
        mcp = MCP23017(i2c_bus, mcp_cfg, loop)
        await mcp.init_setup()
        mcps[mcp_cfg.name] = mcp

    bed_mcp_name = bed_cfg.mcp_port.split(".")[0]
    bed = OkinBed("bed", bed_cfg, mcps[bed_mcp_name])

    remote_mcp_name = remote_cfg.mcp_port.split(".")[0]
    _remote = OkinRemote(bed, remote_cfg, mcps[remote_mcp_name])

    # Wire standalone multibutton if multibutton.json5 is present
    if mb_cfg and mb_cfg.mcp_port:
        mb_mcp_name, mb_port_id = mb_cfg.mcp_port.split(".")
        mb_mcp = mcps.get(mb_mcp_name)
        if mb_mcp is None:
            LOGGER.warning("Standalone MultiButton: unknown MCP device '%s' — skipping", mb_mcp_name)
        else:
            _standalone_mb = MultiButton(bed, mb_cfg)
            mb_port = mb_mcp.get_port(mb_port_id)
            def _on_mb_change(bits: int, value: int, _mb: MultiButton = _standalone_mb) -> None:
                mask = _mb.mask
                if bits & mask:
                    _mb.input_change((value & mask) == 0)
            mb_port.add_change_handler(_on_mb_change)
            LOGGER.info("Standalone MultiButton active mcp_port=%s bit=%d", mb_cfg.mcp_port, mb_cfg.bit)

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        LOGGER.info("Shutdown requested")
        stop_event.set()

    for signame in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signame, _request_stop)

    try:
        await stop_event.wait()
    finally:
        LOGGER.info("Stopping Bedberry core")
        await bed.close()
        for mcp in mcps.values():
            await mcp.close()
        i2c_bus.close()
        GPIO.cleanup()


def main() -> None:
    args = _parse_args()
    _configure_logging(args.verbose)
    try:
        asyncio.run(_run(args))
    except FileNotFoundError as exc:
        available = _list_i2c_buses()
        available_text = ", ".join(str(b) for b in available) if available else "none"
        raise SystemExit(
            f"I2C startup failed: {exc}\n"
            f"Requested bus: {args.i2c_bus}; available buses: {available_text}.\n"
            "Tip: pass --i2c-bus <id> explicitly and verify with: sudo i2cdetect -r -y <id>."
        ) from exc


if __name__ == "__main__":
    main()
