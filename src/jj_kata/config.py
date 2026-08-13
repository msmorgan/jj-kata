from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .errors import KataError

CONFIG_NAME = "jjkata.toml"
LEGACY_CONFIG_NAME = "jjworkflow.toml"


def load_config(root: Path) -> dict[str, Any]:
    legacy = root / LEGACY_CONFIG_NAME
    if legacy.exists():
        raise KataError(
            f"legacy {LEGACY_CONFIG_NAME} state is not accepted by jj-kata 0.11; "
            f"remove or migrate it to {CONFIG_NAME} before using Kata",
            2,
        )
    path = root / CONFIG_NAME
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as config_file:
            return tomllib.load(config_file)
    except tomllib.TOMLDecodeError as error:
        raise KataError(f"invalid {path}: {error}", 2) from error


def find_config(start: Path) -> tuple[Path | None, dict[str, Any]]:
    for directory in (start.resolve(), *start.resolve().parents):
        if (directory / CONFIG_NAME).is_file():
            return directory, load_config(directory)
    return None, {}


def section(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise KataError(f"[{name}] must be a TOML table", 2)
    return value
