from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from typing import Callable


LOGGER = logging.getLogger(__name__)


class MultiButtonState(Enum):
    IDLE = 0
    WAIT_RELEASE_OR_HOLD = 1
    HOLDING = 2
    WAIT_PRESS = 3


@dataclass(frozen=True)
class MultiButtonCoreConfig:
    wait_release: int = 333
    wait_press: int = 333


class MultiButtonCore:
    def __init__(self, cfg: MultiButtonCoreConfig | None = None) -> None:
        self._cfg = cfg or MultiButtonCoreConfig()

        self._state = MultiButtonState.IDLE
        self._pressed = False
        self._click_count = 0
        self._timeout_handle = None

        self._click_handlers: list[Callable[[int], None]] = []
        self._hold_handlers: list[Callable[[int], None]] = []
        self._release_handlers: list[Callable[[int], None]] = []

    def on_click(self, handler: Callable[[int], None]) -> None:
        self._click_handlers.append(handler)

    def on_hold(self, handler: Callable[[int], None]) -> None:
        self._hold_handlers.append(handler)

    def on_release(self, handler: Callable[[int], None]) -> None:
        self._release_handlers.append(handler)

    def update(self, pressed: bool) -> None:
        if pressed == self._pressed:
            return

        if self._state == MultiButtonState.IDLE:
            self._update_idle(pressed)
        elif self._state == MultiButtonState.WAIT_RELEASE_OR_HOLD:
            self._update_wait_release_or_hold(pressed)
        elif self._state == MultiButtonState.HOLDING:
            self._update_holding(pressed)
        elif self._state == MultiButtonState.WAIT_PRESS:
            self._update_wait_press(pressed)
        else:
            self.reset()

    def reset(self) -> None:
        LOGGER.debug("MultiButtonCore reset")
        self._state = MultiButtonState.IDLE
        self._pressed = False
        self._click_count = 0
        self._clear_timeout()

    def _set_state(self, state: MultiButtonState) -> None:
        LOGGER.debug("MultiButtonCore state %s -> %s", self._state.name, state.name)
        self._state = state

    def _set_timeout(self, ms: int) -> None:
        self._clear_timeout()
        import asyncio

        loop = asyncio.get_running_loop()
        self._timeout_handle = loop.call_later(ms / 1000.0, self._handle_timeout)

    def _clear_timeout(self) -> None:
        if self._timeout_handle:
            self._timeout_handle.cancel()
        self._timeout_handle = None

    def _emit_click(self, count: int) -> None:
        LOGGER.debug("MultiButtonCore emit click count=%d", count)
        for handler in self._click_handlers:
            handler(count)

    def _emit_hold(self, count: int) -> None:
        LOGGER.debug("MultiButtonCore emit hold count=%d", count)
        for handler in self._hold_handlers:
            handler(count)

    def _emit_release(self, count: int) -> None:
        LOGGER.debug("MultiButtonCore emit release count=%d", count)
        for handler in self._release_handlers:
            handler(count)

    def _handle_timeout(self) -> None:
        self._clear_timeout()
        if self._state == MultiButtonState.IDLE:
            self.reset()
        elif self._state == MultiButtonState.WAIT_RELEASE_OR_HOLD:
            self._emit_hold(self._click_count)
            self._set_state(MultiButtonState.HOLDING)
        elif self._state == MultiButtonState.HOLDING:
            self.reset()
        elif self._state == MultiButtonState.WAIT_PRESS:
            self._emit_click(self._click_count)
            self.reset()

    def _update_idle(self, pressed: bool) -> None:
        self._pressed = pressed
        if pressed:
            self._set_timeout(self._cfg.wait_release)
            self._set_state(MultiButtonState.WAIT_RELEASE_OR_HOLD)
        else:
            self.reset()

    def _update_wait_release_or_hold(self, pressed: bool) -> None:
        self._pressed = pressed
        if not pressed:
            self._set_timeout(self._cfg.wait_press)
            self._set_state(MultiButtonState.WAIT_PRESS)
        else:
            self.reset()

    def _update_wait_press(self, pressed: bool) -> None:
        self._pressed = pressed
        if pressed:
            self._click_count += 1
            self._set_timeout(self._cfg.wait_release)
            self._set_state(MultiButtonState.WAIT_RELEASE_OR_HOLD)
        else:
            self.reset()

    def _update_holding(self, pressed: bool) -> None:
        self._pressed = pressed
        if not pressed:
            self._emit_release(self._click_count)
            self.reset()
        else:
            self.reset()
