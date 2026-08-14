from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .errors import KataError
from .lifecycle import Lifecycle
from .orientation import orient, render


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
    coordinator: Lifecycle | None = None
    try:
        lifecycle = Lifecycle(cwd)
        coordinator = Lifecycle(lifecycle.default_root)
        with coordinator.lock():
            if name in coordinator.workspace_names():
                coordinator.drop(name)
    except KataError as error:
        # drop can fail after it has already retired the workspace, so read the
        # outcome back rather than reporting every refusal as a preserved one.
        state = "retired" if _is_retired(coordinator, name) else "kept"
        print(f"kata: worktree removal {state} {name}: {error}", file=sys.stderr)
    return 0


def _is_retired(coordinator: Lifecycle | None, name: str) -> bool:
    if coordinator is None:
        return False
    try:
        return name not in coordinator.workspace_names()
    except KataError:
        return False


def session_start() -> int:
    antigravity = False
    try:
        payload = _session_payload()
        antigravity = "invocationNum" in payload
        # Antigravity runs PreInvocation before every model invocation, so only
        # its first one may speak; Claude and Codex deliver one SessionStart and
        # carry no such counter.
        if antigravity and payload.get("invocationNum") != 0:
            return _quiet(True)
        orientation = orient(_session_cwd(payload))
        if orientation is None:
            return _quiet(antigravity)
        text = render(orientation)
        if antigravity:
            print(json.dumps({"injectSteps": [{"ephemeralMessage": text}]}))
        else:
            print(text, end="")
    # Orientation is a convenience, and a session that cannot start is not. Every
    # failure here — an unreadable payload, a jj that will not answer, a bug this
    # module has yet to grow — ends as silence rather than a blocked session.
    except Exception:  # noqa: BLE001
        return _quiet(antigravity)
    return 0


def _session_payload() -> dict[str, object]:
    """Read a host payload, tolerating hosts that send nothing at all."""
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _session_cwd(payload: dict[str, object]) -> Path:
    mounted = payload.get("workspacePaths")
    if isinstance(mounted, list) and mounted:
        return Path(str(mounted[0]))
    location = payload.get("cwd")
    return Path(str(location)) if location else Path.cwd()


def _quiet(antigravity: bool) -> int:
    if antigravity:
        print("{}")
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


def session_start_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="session_start.py",
        description=(
            "Describe the Kata repository a session started in, reading a "
            "SessionStart or PreInvocation JSON payload."
        ),
    )
    parser.parse_args(argv)
    return session_start()
