from __future__ import annotations

import asyncio
import logging
import urllib.request
from typing import Callable

from .config import MultiButtonAction, MultiButtonActionTypes, MultiButtonConfig
from .multibutton_core import MultiButtonCore, MultiButtonCoreConfig
from .okin_bed import OkinBed


LOGGER = logging.getLogger(__name__)


class MultiButton:
    def __init__(self, okin_bed: OkinBed, cfg: MultiButtonConfig) -> None:
        self._okin_bed = okin_bed
        self._mask = 1 << cfg.bit

        self._core = MultiButtonCore(
            MultiButtonCoreConfig(
                wait_release=cfg.timings.wait_release,
                wait_press=cfg.timings.wait_press,
            )
        )
        self._on_release: Callable[[], None] | None = None
        self._current_action: str | None = None

        self._on_click: list[Callable[[], None] | None] = []
        self._on_hold: list[Callable[[], None] | None] = []

        self._core.on_click(self._handle_click)
        self._core.on_hold(self._handle_hold)
        self._core.on_release(lambda _count: self._handle_release())

        self._setup_actions(cfg.actions)
        LOGGER.info("MultiButton configured bit=%d mask=0x%02x", cfg.bit, self._mask)

    @property
    def mask(self) -> int:
        return self._mask

    def input_change(self, pressed: bool) -> None:
        LOGGER.debug("MultiButton input pressed=%s mask=0x%02x", pressed, self._mask)
        self._core.update(pressed)

    def _handle_click(self, count: int) -> None:
        LOGGER.debug("MultiButton click count=%d", count)
        self._current_action = "click"
        handler = self._on_click[count] if count < len(self._on_click) else None
        if handler:
            handler()
        self._current_action = None

    def _handle_hold(self, count: int) -> None:
        LOGGER.debug("MultiButton hold count=%d", count)
        self._current_action = "hold"
        handler = self._on_hold[count] if count < len(self._on_hold) else None
        if handler:
            handler()

    def _handle_release(self) -> None:
        LOGGER.debug("MultiButton release")
        self._current_action = None
        if self._on_release:
            self._on_release()
        self._on_release = None

    def _setup_actions(self, actions: list[MultiButtonActionTypes]) -> None:
        for idx, action in enumerate(actions):
            if len(self._on_click) <= idx:
                self._on_click.append(None)
                self._on_hold.append(None)

            if action.click is not None:
                self._on_click[idx] = self._calc_handler(action.click)
            elif action.hold is not None:
                self._on_hold[idx] = self._calc_handler(action.hold)

    def _calc_handler(self, action: MultiButtonAction) -> Callable[[], None]:
        action_type = action.type.lower()
        if action_type == "url":
            return lambda: asyncio.create_task(self._on_url(action.data))
        if action_type == "ext":
            return lambda: asyncio.create_task(self._on_ext(action.data))
        return lambda: asyncio.create_task(self._on_bed(action.data))

    async def _on_bed(self, details: dict) -> None:
        actuator = str(details["actuator"])
        dir_is_up = bool(details["dirIsUp"])
        period = float(details.get("period", 60))

        LOGGER.info("MultiButton bed action actuator=%s dir=%s duration=%.2f", actuator, "UP" if dir_is_up else "DOWN", period)

        await self._okin_bed.move(actuator, dir_is_up, period)
        if self._current_action == "hold":
            self._on_release = lambda: asyncio.create_task(self._okin_bed.stop(actuator))

    async def _on_ext(self, details: dict) -> None:
        command = str(details["command"])
        timeout_ms = int(details.get("timeout", 60000))
        cwd = details.get("cwd")
        LOGGER.info("MultiButton ext action command=%s", command)

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            LOGGER.warning("MultiButton ext action timeout command=%s", command)
            proc.kill()
            await proc.wait()

    async def _on_url(self, details: dict) -> None:
        url = str(details["url"])
        LOGGER.info("MultiButton url action url=%s", url)

        def _fetch() -> None:
            with urllib.request.urlopen(url, timeout=10) as _resp:
                _resp.read()

        await asyncio.to_thread(_fetch)
