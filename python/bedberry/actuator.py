from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import logging

from .config import ActuatorConfig
from .mcp23017 import MCP23017Port


LOGGER = logging.getLogger(__name__)


class ActuatorCmdType(str, Enum):
    STOP = "stop"
    MOVE = "move"
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class ActuatorCmd:
    type: ActuatorCmdType
    duration: float = 30.0
    dir_is_up: bool = True


class ActuatorState(str, Enum):
    STOPPED = "stopped"
    MOVING = "moving"


class Actuator:
    def __init__(self, name: str, mcp_port: MCP23017Port, cfg: ActuatorConfig) -> None:
        self._name = name
        self._mcp_port = mcp_port
        self._cfg = cfg

        self._state = ActuatorState.STOPPED
        self._cmd_queue: asyncio.Queue[ActuatorCmd] = asyncio.Queue()
        self._stop_task: asyncio.Task[None] | None = None
        self._worker = asyncio.create_task(self._process_queue())
        LOGGER.info("Actuator %s configured (up=%d down=%d)", self._name, cfg.up, cfg.down)

    async def command(self, cmd: ActuatorCmd) -> None:
        LOGGER.debug("Actuator %s command %s", self._name, cmd)
        await self._cmd_queue.put(self._normalize(cmd))

    async def move(self, dir_is_up: bool, duration: float = 30.0) -> None:
        await self.command(
            ActuatorCmd(
                type=ActuatorCmdType.MOVE,
                duration=duration,
                dir_is_up=dir_is_up,
            )
        )

    async def stop(self) -> None:
        await self.command(ActuatorCmd(type=ActuatorCmdType.STOP, duration=0))

    async def _process_queue(self) -> None:
        while True:
            cmd = await self._cmd_queue.get()
            if cmd.type == ActuatorCmdType.STOP:
                await self._apply_stop()
                self._state = ActuatorState.STOPPED
            elif cmd.type == ActuatorCmdType.MOVE:
                await self._apply_move(cmd.dir_is_up)
                self._state = ActuatorState.MOVING
                self._arm_auto_stop(cmd.duration)
            self._cmd_queue.task_done()

    async def _apply_move(self, dir_is_up: bool) -> None:
        LOGGER.info("Actuator %s move %s", self._name, "UP" if dir_is_up else "DOWN")
        await self._cancel_auto_stop()
        await self._mcp_port.set_bit(self._cfg.down, dir_is_up)
        await self._mcp_port.set_bit(self._cfg.up, not dir_is_up)

    async def _apply_stop(self) -> None:
        LOGGER.info("Actuator %s stop", self._name)
        await self._cancel_auto_stop()
        await self._mcp_port.set_bit(self._cfg.down, True)
        await self._mcp_port.set_bit(self._cfg.up, True)

    def _arm_auto_stop(self, duration: float) -> None:
        LOGGER.debug("Actuator %s auto-stop in %.2f sec", self._name, duration)
        self._stop_task = asyncio.create_task(self._auto_stop(duration))

    async def _auto_stop(self, duration: float) -> None:
        await asyncio.sleep(max(duration, 0.0))
        await self._apply_stop()
        self._state = ActuatorState.STOPPED

    async def _cancel_auto_stop(self) -> None:
        if not self._stop_task:
            return
        self._stop_task.cancel()
        try:
            await self._stop_task
        except asyncio.CancelledError:
            pass
        self._stop_task = None

    def _normalize(self, cmd: ActuatorCmd) -> ActuatorCmd:
        if cmd.type == ActuatorCmdType.UP:
            return ActuatorCmd(type=ActuatorCmdType.MOVE, dir_is_up=True, duration=cmd.duration)
        if cmd.type == ActuatorCmdType.DOWN:
            return ActuatorCmd(type=ActuatorCmdType.MOVE, dir_is_up=False, duration=cmd.duration)
        return cmd

    async def close(self) -> None:
        LOGGER.info("Closing actuator %s", self._name)
        await self._cancel_auto_stop()
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
