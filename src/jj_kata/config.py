from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .errors import KataError

CONFIG_NAMES = ("jjkata.toml", "jjworkflow.toml")


def load_config(root: Path) -> dict[str, Any]:
    for name in CONFIG_NAMES:
        path = root / name
        if not path.is_file():
            continue
        try:
            with path.open("rb") as config_file:
                return tomllib.load(config_file)
        except tomllib.TOMLDecodeError as error:
            raise KataError(f"invalid {path}: {error}", 2) from error
    return {}


def find_config(start: Path) -> tuple[Path | None, dict[str, Any]]:
    for directory in (start.resolve(), *start.resolve().parents):
        if any((directory / name).is_file() for name in CONFIG_NAMES):
            return directory, load_config(directory)
    return None, {}


def section(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise KataError(f"[{name}] must be a TOML table", 2)
    return value
