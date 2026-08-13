from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .errors import KataError
from .lifecycle import Lifecycle


def _payload() -> dict[str, object]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as error:
        raise KataError(f"invalid worktree hook input: {error}", 2) from error
    if not isinstance(value, dict):
        raise KataError("worktree hook input must be a JSON object", 2)
    return value


def worktree_create() -> int:
    data = _payload()
    name = str(data.get("name") or data.get("worktree_name") or "")
    cwd = Path(str(data.get("cwd") or Path.cwd()))
    if not name:
        raise KataError("worktree hook input has no name", 2)
    probe = Lifecycle(cwd)
    lifecycle = Lifecycle(probe.default_root)
    with lifecycle.lock():
        path = lifecycle.claim([name], or_start=True)
    if path:
        print(path)
    return 0


def worktree_remove() -> int:
    data = _payload()
    cwd = Path(str(data.get("cwd") or Path.cwd()))
    worktree_path = Path(str(data.get("worktree_path") or cwd))
    name = str(data.get("name") or data.get("worktree_name") or worktree_path.name)
    try:
        lifecycle = Lifecycle(cwd)
        coordinator = Lifecycle(lifecycle.default_root)
        with coordinator.lock():
            if name in coordinator.workspace_names():
                coordinator.drop(name)
    except KataError as error:
        print(f"kata: worktree removal kept {name}: {error}", file=sys.stderr)
    return 0


def worktree_create_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="worktree_create.py",
        description="Create a Kata workspace from a worktree-hook JSON payload.",
    )
    parser.parse_args(argv)
    try:
        return worktree_create()
    except KataError as error:
        print(f"kata: {error}", file=sys.stderr)
        return error.code


def worktree_remove_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="worktree_remove.py",
        description="Retire a Kata workspace from a worktree-hook JSON payload.",
    )
    parser.parse_args(argv)
    try:
        return worktree_remove()
    except KataError as error:
        print(f"kata: worktree removal skipped: {error}", file=sys.stderr)
        return 0
