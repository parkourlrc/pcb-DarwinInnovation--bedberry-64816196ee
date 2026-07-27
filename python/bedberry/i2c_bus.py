from __future__ import annotations

import asyncio
import logging
from smbus2 import SMBus


LOGGER = logging.getLogger(__name__)


class WbI2cBus:
    def __init__(self, bus_id: int) -> None:
        self._bus_id = bus_id
        self._bus = SMBus(bus_id)
        self._lock = asyncio.Lock()
        LOGGER.info("Opened I2C bus %d", bus_id)

    async def write_byte(self, addr: int, reg: int, data: int) -> None:
        LOGGER.debug("i2c-%d write addr=0x%02x reg=0x%02x data=0x%02x", self._bus_id, addr, reg, data)
        async with self._lock:
            await asyncio.to_thread(
                self._bus.write_i2c_block_data,
                addr,
                reg,
                [data & 0xFF],
            )

    async def read_byte(self, addr: int, reg: int) -> int:
        async with self._lock:
            result = await asyncio.to_thread(self._bus.read_byte_data, addr, reg)
        LOGGER.debug("i2c-%d read  addr=0x%02x reg=0x%02x data=0x%02x", self._bus_id, addr, reg, result)
        return result

    def close(self) -> None:
        LOGGER.info("Closing I2C bus %d", self._bus_id)
        self._bus.close()
