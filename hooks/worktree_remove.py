#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from jj_workflow.hooks import worktree_remove

raise SystemExit(worktree_remove())
