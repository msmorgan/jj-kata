from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .config import section
from .errors import KataError


@dataclass(frozen=True)
class Transition:
    items: tuple[str, ...]
    paths: tuple[str, ...]


class ItemDriver(Protocol):
    def transition(
        self,
        action: str,
        *,
        root: Path,
        workspace: str,
        requested: tuple[str, ...] = (),
        base_revision: str | None = None,
        revision: str | None = None,
        visibility: str = "feature",
    ) -> Transition: ...


def _safe_paths(root: Path, values: object) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(
        isinstance(item, str) for item in values
    ):
        raise KataError("item driver JSON must contain a string-array 'paths'", 2)
    paths: list[str] = []
    for value in values:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in {"", "."}:
            raise KataError(f"item driver returned an unsafe path: {value!r}", 2)
        resolved = (root / Path(*path.parts)).resolve(strict=False)
        try:
            resolved.relative_to(root.resolve())
        except ValueError as error:
            raise KataError(
                f"item driver path escapes the workspace: {value!r}", 2
            ) from error
        paths.append(path.as_posix())
    return tuple(dict.fromkeys(paths))


def _items(values: object) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(
        isinstance(item, str) for item in values
    ):
        raise KataError("item driver JSON must contain a string-array 'items'", 2)
    if any(not item for item in values):
        raise KataError("item driver returned an empty item ID", 2)
    if len(set(values)) != len(values):
        raise KataError("item driver returned duplicate item IDs", 2)
    return tuple(values)


class ExternalDriver:
    def __init__(self, command: tuple[str, ...], default_root: Path) -> None:
        if not command:
            raise KataError("external command may not be empty", 2)
        executable = Path(command[0]).expanduser()
        if not executable.is_absolute() and "/" in command[0]:
            executable = default_root / executable
        self.command = (str(executable), *command[1:])

    def transition(
        self,
        action: str,
        *,
        root: Path,
        workspace: str,
        requested: tuple[str, ...] = (),
        base_revision: str | None = None,
        revision: str | None = None,
        visibility: str = "feature",
    ) -> Transition:
        payload = {
            "version": 1,
            "action": action,
            "workspace": workspace,
            "requested": list(requested),
            "context": {
                "base_revision": base_revision,
                "revision": revision,
                "visibility": visibility,
            },
        }
        process = subprocess.run(
            [*self.command, action, *requested],
            cwd=root,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env={
                **os.environ,
                "JJ_KATA_ACTION": action,
                "JJ_KATA_WORKSPACE": workspace,
            },
            check=False,
        )
        if process.returncode:
            detail = process.stderr.strip() or process.stdout.strip()
            raise KataError(
                detail or f"item driver failed during {action}", process.returncode
            )
        try:
            value = json.loads(process.stdout or "{}")
        except json.JSONDecodeError as error:
            raise KataError(f"item driver returned invalid JSON: {error}", 2) from error
        if not isinstance(value, dict):
            raise KataError("item driver must return one JSON object", 2)
        default_items = [] if action in {"owned", "probe"} else list(requested)
        return Transition(
            _items(value.get("items", default_items)),
            _safe_paths(root, value.get("paths", [])),
        )

    def inspect(self, arguments: list[str], *, cwd: Path) -> int:
        return subprocess.run(
            [*self.command, *arguments], cwd=cwd, check=False
        ).returncode


def external_command(
    value: object, *, setting: str = "items.driver"
) -> tuple[str, ...]:
    if isinstance(value, str):
        command = tuple(shlex.split(value))
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        command = tuple(value)
    else:
        raise KataError(f"{setting} must be a command string or string array", 2)
    if not command:
        raise KataError(f"{setting} may not be empty", 2)
    return command


def load_driver(config: dict[str, Any], default_root: Path) -> ItemDriver | None:
    items_config = section(config, "items")
    value = items_config.get("driver")
    if value is None:
        return None
    if value == "kanban":
        from .kanban import FolderKanbanDriver

        return FolderKanbanDriver.from_config(config, default_root)
    return ExternalDriver(external_command(value), default_root)
