from __future__ import annotations

import logging

from .actuator import Actuator
from .config import OkinBedConfig
from .mcp23017 import MCP23017


LOGGER = logging.getLogger(__name__)


class OkinBed:
    def __init__(self, name: str, cfg: OkinBedConfig, mcp: MCP23017) -> None:
        self._name = name
        self._cfg = cfg
        LOGGER.info("Creating OkinBed %s on port %s", name, cfg.mcp_port)

        mcp_name, port_id = cfg.mcp_port.split(".")
        if mcp_name != mcp.name:
            raise ValueError(f"Expected mcp name {mcp.name}, got {mcp_name}")

        mcp_port = mcp.get_port(port_id)

        self._actuators: dict[str, Actuator] = {
            "head": Actuator(f"{name}.head", mcp_port, cfg.head),
            "feet": Actuator(f"{name}.feet", mcp_port, cfg.feet),
        }
        if cfg.platform:
            self._actuators["platform"] = Actuator(
                f"{name}.platform",
                mcp_port,
                cfg.platform,
            )

    async def move(self, actuator: str, dir_is_up: bool, duration: float = 60.0) -> None:
        LOGGER.debug(
            "OkinBed move actuator=%s dir=%s duration=%.2f",
            actuator,
            "UP" if dir_is_up else "DOWN",
            duration,
        )
        await self._actuators[actuator].move(dir_is_up, duration)

    async def up(self, actuator: str, duration: float = 60.0) -> None:
        await self.move(actuator, True, duration)

    async def down(self, actuator: str, duration: float = 60.0) -> None:
        await self.move(actuator, False, duration)

    async def stop(self, actuator: str) -> None:
        LOGGER.debug("OkinBed stop actuator=%s", actuator)
        await self._actuators[actuator].stop()

    async def stop_all(self) -> None:
        LOGGER.info("OkinBed stop_all")
        for actuator in self._actuators.values():
            await actuator.stop()

    async def close(self) -> None:
        LOGGER.info("Closing OkinBed %s", self._name)
        for actuator in self._actuators.values():
            await actuator.close()
