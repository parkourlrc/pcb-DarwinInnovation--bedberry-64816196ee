from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Awaitable, Callable

import RPi.GPIO as GPIO

from .config import MCP23017DeviceConfig, MCP23017PortDetails
from .i2c_bus import WbI2cBus


LOGGER = logging.getLogger(__name__)


class MCP23017Reg(IntEnum):
    IODIR = 0x00
    IPOL = 0x02
    GPINTEN = 0x04
    DEFVAL = 0x06
    INTCON = 0x08
    IOCON = 0x0A
    GPPU = 0x0C
    INTF = 0x0E
    INTCAP = 0x10
    GPIO = 0x12
    OLAT = 0x14


ChangeHandler = Callable[[int, int], Awaitable[None] | None]


@dataclass(frozen=True)
class MCP23017PortId:
    value: str

    @property
    def offset(self) -> int:
        return 0 if self.value.upper() == "A" else 1


PORT_A = MCP23017PortId("A")
PORT_B = MCP23017PortId("B")


class MCP23017Port:
    def __init__(
        self,
        mcp: "MCP23017",
        port: MCP23017PortId,
        details: MCP23017PortDetails,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._mcp = mcp
        self._offset = port.offset
        self._details = details
        self._loop = loop
        self._cur_rd_value = details.default & details.read_bits
        self._cur_wr_value = details.default & details.write_bits
        self._handlers: list[ChangeHandler] = []
        self._poll_task: asyncio.Task[None] | None = None
        self._port_name = port.value.upper()

    async def init_setup(self) -> None:
        LOGGER.info("Init MCP23017 port %s", self._port_name)
        await self.write_reg(MCP23017Reg.IODIR, 0xFF ^ self._details.write_bits)
        await self.write_reg(MCP23017Reg.GPPU, 0xFF)
        await self.write_reg(MCP23017Reg.OLAT, 0x00)
        await self.write_reg(MCP23017Reg.GPINTEN, 0x00)
        await self.write_reg(MCP23017Reg.DEFVAL, 0x00)
        await self.write_reg(MCP23017Reg.IPOL, 0x00)
        await self.write_reg(MCP23017Reg.INTCON, 0x00)
        await self.read_reg(MCP23017Reg.INTCAP)
        await self.read_reg(MCP23017Reg.GPIO)

        if self._details.write_bits:
            await self.write_reg(MCP23017Reg.GPIO, self._details.write_bits)

        if self._details.int_gpio is not None:
            if self._details.int_on_change:
                await self.write_reg(MCP23017Reg.INTCON, 0xFF ^ self._details.read_bits)
            else:
                await self.write_reg(MCP23017Reg.DEFVAL, self._details.default)
                await self.write_reg(MCP23017Reg.INTCON, self._details.read_bits)
            await self.write_reg(MCP23017Reg.GPINTEN, self._details.read_bits)

        if self._details.poll_period > 0:
            LOGGER.info(
                "MCP23017 port %s polling enabled every %d ms",
                self._port_name,
                self._details.poll_period,
            )
            self._poll_task = asyncio.create_task(self._poll_loop())

    def add_change_handler(self, handler: ChangeHandler) -> None:
        self._handlers.append(handler)

    async def set(self, value: int) -> None:
        value = value & self._details.write_bits
        self._cur_wr_value = value
        await self.write_reg(MCP23017Reg.OLAT, value)

    async def set_bit(self, bit: int, value: bool) -> None:
        bit_mask = 1 << bit
        new_value = (self._cur_wr_value & (0xFF ^ bit_mask)) | (bit_mask if value else 0)
        await self.set(new_value)

    async def write_reg(self, reg: MCP23017Reg, data: int) -> None:
        await self._mcp.write_byte(int(reg) + self._offset, data)

    async def read_reg(self, reg: MCP23017Reg) -> int:
        return await self._mcp.read_byte(int(reg) + self._offset)

    async def on_interrupt(self) -> None:
        LOGGER.debug("MCP23017 port %s interrupt", self._port_name)
        gpio_value = await self.read_reg(MCP23017Reg.GPIO)
        await self._update(gpio_value)

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._details.poll_period / 1000.0)
            gpio_value = await self.read_reg(MCP23017Reg.GPIO)
            await self._update(gpio_value)

    async def _update(self, value: int) -> None:
        diff = (value ^ self._cur_rd_value) & self._details.read_bits
        self._cur_rd_value = value
        if not diff:
            return

        LOGGER.debug(
            "MCP23017 port %s change diff=0x%02x value=0x%02x",
            self._port_name,
            diff,
            value,
        )

        for handler in self._handlers:
            try:
                maybe = handler(diff, value)
                if asyncio.iscoroutine(maybe):
                    await maybe
            except Exception:
                LOGGER.exception("MCP23017 port %s change handler failed", self._port_name)

    async def close(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass


class MCP23017:
    def __init__(
        self,
        bus: WbI2cBus,
        cfg: MCP23017DeviceConfig,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.name = cfg.name
        self.address = cfg.address
        self._bus = bus
        self._cfg = cfg
        self._loop = loop

        self._ports = {
            "A": MCP23017Port(self, PORT_A, cfg.details_a, loop),
            "B": MCP23017Port(self, PORT_B, cfg.details_b, loop),
        }

        # Semantic aliases used in config files (e.g. "okin.input", "okin.output")
        _PORT_ALIASES: dict[str, str] = {"INPUT": "A", "OUTPUT": "B"}

        self._gpio_callbacks: dict[int, Callable[[int], None]] = {}
        LOGGER.info("Configured MCP23017 name=%s address=0x%02x", self.name, self.address)

    def get_port(self, port: str) -> MCP23017Port:
        key = port.upper()
        key = {"INPUT": "A", "OUTPUT": "B"}.get(key, key)
        return self._ports[key]

    async def init_setup(self) -> None:
        LOGGER.info("Initializing MCP23017 registers")
        await self.write_byte(MCP23017Reg.IOCON, 0x00)
        await self.get_port("A").init_setup()
        await self.get_port("B").init_setup()

        self._setup_interrupts()

    async def write_byte(self, reg: int | MCP23017Reg, data: int) -> None:
        await self._bus.write_byte(self.address, int(reg), data)

    async def read_byte(self, reg: int | MCP23017Reg) -> int:
        return await self._bus.read_byte(self.address, int(reg))

    def _setup_interrupts(self) -> None:
        for port_id, details in (("A", self._cfg.details_a), ("B", self._cfg.details_b)):
            if details.int_gpio is None:
                continue
            gpio = int(details.int_gpio)
            port = self.get_port(port_id)

            def _make_cb(target_port: MCP23017Port) -> Callable[[int], None]:
                def _cb(_: int) -> None:
                    self._loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(target_port.on_interrupt())
                    )

                return _cb

            cb = _make_cb(port)
            self._gpio_callbacks[gpio] = cb
            GPIO.setup(gpio, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(gpio, GPIO.FALLING, callback=cb)
            LOGGER.info("MCP23017 port %s interrupt on GPIO %d", port_id, gpio)

    async def close(self) -> None:
        LOGGER.info("Closing MCP23017")
        for gpio in self._gpio_callbacks:
            try:
                GPIO.remove_event_detect(gpio)
            except RuntimeError:
                pass
        self._gpio_callbacks.clear()

        await self.get_port("A").close()
        await self.get_port("B").close()
