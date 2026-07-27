from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class MCP23017PortDetails:
    int_gpio: int | None = None
    int_on_change: bool = True
    default: int = 0x00
    read_bits: int = 0xFF
    write_bits: int = 0x00
    poll_period: int = 0


@dataclass
class MCP23017DeviceConfig:
    address: int
    name: str
    type: str
    details_a: MCP23017PortDetails
    details_b: MCP23017PortDetails


@dataclass
class ActuatorConfig:
    up: int
    down: int


@dataclass
class OkinBedConfig:
    mcp_port: str
    head: ActuatorConfig
    feet: ActuatorConfig
    platform: ActuatorConfig | None
    max_move_duration: int


@dataclass
class MultiButtonTimings:
    wait_release: int = 333
    wait_press: int = 333


@dataclass
class MultiButtonAction:
    type: str
    data: dict[str, Any]


@dataclass
class MultiButtonActionTypes:
    click: MultiButtonAction | None = None
    hold: MultiButtonAction | None = None


@dataclass
class MultiButtonConfig:
    bit: int
    timings: MultiButtonTimings
    actions: list[MultiButtonActionTypes]
    mcp_port: str = ""


@dataclass
class OkinRemoteDirMap:
    up: int
    down: int


@dataclass
class OkinRemoteConfig:
    mcp_port: str
    head: OkinRemoteDirMap
    feet: OkinRemoteDirMap
    platform: OkinRemoteDirMap | None
    multibuttons: list[MultiButtonConfig]


def _load_yaml(path: Path) -> Any:
    """Load a YAML config file, supporting both .yaml and .yml extensions."""
    # Try .yaml first, then .yml
    for ext in (".yaml", ".yml"):
        try_path = path.parent / (path.stem + ext)
        if try_path.exists():
            with try_path.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f)
    raise FileNotFoundError(f"Config file not found: {path.stem}{{.yaml,.yml}} in {path.parent}")


def _parse_port_details(raw: dict[str, Any] | None) -> MCP23017PortDetails:
    raw = raw or {}
    return MCP23017PortDetails(
        int_gpio=raw.get("int_gpio"),
        int_on_change=raw.get("int_on_change", True),
        default=raw.get("default", 0x00),
        read_bits=raw.get("read_bits", 0xFF),
        write_bits=raw.get("write_bits", 0x00),
        poll_period=raw.get("poll_period", 0),
    )


def _parse_port_details_by_name(details: dict[str, Any], *keys: str) -> MCP23017PortDetails:
    """Try each key in order, returning the first match (or defaults if none found)."""
    for key in keys:
        raw = details.get(key)
        if raw is not None:
            return _parse_port_details(raw)
    return _parse_port_details(None)


def load_all_mcp23017_from_i2c_config(config_dir: Path) -> list[MCP23017DeviceConfig]:
    """Load all MCP23017 device configs from i2c.yaml.

    Port A is keyed as ``"input"`` or ``"A"`` in the config file.
    Port B is keyed as ``"output"`` or ``"B"``.
    """
    i2c_cfg = _load_yaml(config_dir / "i2c.yaml")
    if not isinstance(i2c_cfg, list) or not i2c_cfg:
        raise ValueError("i2c.json5 must contain at least one device")

    result: list[MCP23017DeviceConfig] = []
    for dev in i2c_cfg:
        details = dev.get("details", {})
        details_a = _parse_port_details_by_name(details, "input", "A")
        details_b = _parse_port_details_by_name(details, "output", "B")
        result.append(MCP23017DeviceConfig(
            address=int(dev["address"]),
            name=str(dev["name"]),
            type=str(dev["type"]),
            details_a=details_a,
            details_b=details_b,
        ))
    return result


def load_okin_bed_config(config_dir: Path) -> OkinBedConfig:
    raw = _load_yaml(config_dir / "okin.yaml")

    platform = raw.get("platform")
    return OkinBedConfig(
        mcp_port=str(raw["mcp_port"]),
        head=ActuatorConfig(**raw["head"]),
        feet=ActuatorConfig(**raw["feet"]),
        platform=ActuatorConfig(**platform) if platform else None,
        max_move_duration=int(raw.get("max_move_duration", 60)),
    )


def _parse_mb_action(raw: dict[str, Any] | None) -> MultiButtonAction | None:
    if not raw:
        return None
    action_type = str(raw.get("type", "")).lower()
    return MultiButtonAction(type=action_type, data=dict(raw))


def _parse_mb_actions(raw_actions: list[dict[str, Any]]) -> list[MultiButtonActionTypes]:
    parsed: list[MultiButtonActionTypes] = []
    for entry in raw_actions:
        click = _parse_mb_action(entry.get("click"))
        hold = _parse_mb_action(entry.get("hold"))
        parsed.append(MultiButtonActionTypes(click=click, hold=hold))
    return parsed


def _parse_multibutton(raw: dict[str, Any]) -> MultiButtonConfig:
    timings_raw = raw.get("timings", {})
    timings = MultiButtonTimings(
        wait_release=int(timings_raw.get("wait_release", 333)),
        wait_press=int(timings_raw.get("wait_press", 333)),
    )
    return MultiButtonConfig(
        bit=int(raw["bit"]),
        timings=timings,
        actions=_parse_mb_actions(raw.get("actions", [])),
    )


def load_multibutton_config(config_dir: Path) -> MultiButtonConfig | None:
    """Load the standalone multibutton.yaml, returning None if the file is absent."""
    try:
        raw = _load_yaml(config_dir / "multibutton.yaml")
    except FileNotFoundError:
        return None
    cfg = _parse_multibutton(raw)
    cfg.mcp_port = str(raw.get("mcp_port", ""))
    return cfg


def load_okin_remote_config(config_dir: Path) -> OkinRemoteConfig:
    raw = _load_yaml(config_dir / "okinRemote.yaml")

    mb_cfgs = [_parse_multibutton(item) for item in raw.get("multibuttons", [])]
    platform = raw.get("platform")

    return OkinRemoteConfig(
        mcp_port=str(raw["mcp_port"]),
        head=OkinRemoteDirMap(**raw["head"]),
        feet=OkinRemoteDirMap(**raw["feet"]),
        platform=OkinRemoteDirMap(**platform) if platform else None,
        multibuttons=mb_cfgs,
    )
