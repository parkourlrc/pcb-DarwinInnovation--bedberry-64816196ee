from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from .config import OkinRemoteConfig
from .mcp23017 import MCP23017
from .multibutton import MultiButton
from .okin_bed import OkinBed


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ActuatorDir:
    actuator: str
    dir_is_up: bool


class OkinRemote:
    def __init__(self, okin_bed: OkinBed, cfg: OkinRemoteConfig, mcp: MCP23017) -> None:
        self._okin_bed = okin_bed
        self._cfg = cfg

        mcp_name, port_id = cfg.mcp_port.split(".")
        if mcp_name != mcp.name:
            raise ValueError(f"Expected mcp name {mcp.name}, got {mcp_name}")

        self._mcp_port = mcp.get_port(port_id)
        self._mcp_port.add_change_handler(self._on_change)
        LOGGER.info("OkinRemote attached to port %s", cfg.mcp_port)

        self._bit_to_actuator: dict[int, _ActuatorDir] = {
            cfg.head.up: _ActuatorDir(actuator="head", dir_is_up=True),
            cfg.head.down: _ActuatorDir(actuator="head", dir_is_up=False),
            cfg.feet.up: _ActuatorDir(actuator="feet", dir_is_up=True),
            cfg.feet.down: _ActuatorDir(actuator="feet", dir_is_up=False),
        }

        self._bed_mask = (
            (1 << cfg.head.up)
            | (1 << cfg.head.down)
            | (1 << cfg.feet.up)
            | (1 << cfg.feet.down)
        )

        if cfg.platform is not None:
            self._bit_to_actuator[cfg.platform.up] = _ActuatorDir(
                actuator="platform", dir_is_up=True
            )
            self._bit_to_actuator[cfg.platform.down] = _ActuatorDir(
                actuator="platform", dir_is_up=False
            )
            self._bed_mask |= (1 << cfg.platform.up) | (1 << cfg.platform.down)

        self._multibuttons = [MultiButton(okin_bed, mb_cfg) for mb_cfg in cfg.multibuttons]
        self._mb_mask = 0
        for mb in self._multibuttons:
            self._mb_mask |= mb.mask
        LOGGER.info("OkinRemote masks bed=0x%02x multibutton=0x%02x", self._bed_mask, self._mb_mask)

    def _on_change(self, bits: int, value: int) -> None:
        LOGGER.debug("OkinRemote change bits=0x%02x value=0x%02x", bits, value)
        asyncio.create_task(self._handle_change(bits, value))

    async def _handle_change(self, bits: int, value: int) -> None:
        if bits & self._mb_mask:
            self._on_mb_change(bits & self._mb_mask, value & self._mb_mask)

        if bits & self._bed_mask:
            await self._on_bed_change(bits & self._bed_mask, value & self._bed_mask)

    def _on_mb_change(self, bits: int, value: int) -> None:
        for mb in self._multibuttons:
            mask = mb.mask
            if bits & mask:
                LOGGER.debug("OkinRemote multibutton change mask=0x%02x pressed=%s", mask, (value & mask) == 0)
                mb.input_change((value & mask) == 0)
                bits &= ~mask
                value &= ~mask

    async def _on_bed_change(self, bits: int, value: int) -> None:
        if value == 0:
            LOGGER.info("OkinRemote all bed bits low -> stop_all")
            await self._okin_bed.stop_all()
            return

        bit = 0
        while bits:
            bit_value = 1 << bit
            if bits & bit_value:
                actuator_dir = self._bit_to_actuator.get(bit)
                if actuator_dir is not None:
                    if value & bit_value:
                        LOGGER.info("OkinRemote start %s %s", actuator_dir.actuator, "UP" if actuator_dir.dir_is_up else "DOWN")
                        await self._okin_bed.move(actuator_dir.actuator, actuator_dir.dir_is_up, 60)
                    else:
                        LOGGER.info("OkinRemote stop %s", actuator_dir.actuator)
                        await self._okin_bed.stop(actuator_dir.actuator)
                bits ^= bit_value
            bit += 1
