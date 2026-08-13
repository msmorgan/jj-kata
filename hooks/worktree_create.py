#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from jj_workflow.errors import WorkflowError
from jj_workflow.hooks import worktree_create

try:
    raise SystemExit(worktree_create())
except WorkflowError as error:
    print(f"workflow: {error}", file=sys.stderr)
    raise SystemExit(error.code) from error
