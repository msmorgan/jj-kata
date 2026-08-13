from __future__ import annotations

import json
import sys
from pathlib import Path

from .errors import WorkflowError
from .workflow import Workflow


def _payload() -> dict[str, object]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as error:
        raise WorkflowError(f"invalid worktree hook input: {error}", 2) from error
    if not isinstance(value, dict):
        raise WorkflowError("worktree hook input must be a JSON object", 2)
    return value


def worktree_create() -> int:
    data = _payload()
    name = str(data.get("name") or data.get("worktree_name") or "")
    cwd = Path(str(data.get("cwd") or Path.cwd()))
    if not name:
        raise WorkflowError("worktree hook input has no name", 2)
    probe = Workflow(cwd)
    workflow = Workflow(probe.default_root)
    with workflow.lock():
        path = workflow.claim([name], or_start=True)
    if path:
        print(path)
    return 0


def worktree_remove() -> int:
    data = _payload()
    cwd = Path(str(data.get("cwd") or Path.cwd()))
    worktree_path = Path(str(data.get("worktree_path") or cwd))
    name = str(data.get("name") or data.get("worktree_name") or worktree_path.name)
    try:
        workflow = Workflow(cwd)
        coordinator = Workflow(workflow.default_root)
        with coordinator.lock():
            if name in coordinator.workspace_names():
                coordinator.drop(name)
    except WorkflowError as error:
        print(f"workflow: worktree removal kept {name}: {error}", file=sys.stderr)
    return 0
