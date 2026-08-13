from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_manifests_describe_workflow_and_kanban_plugin() -> None:
    codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    antigravity = json.loads((ROOT / "plugin.json").read_text())

    assert codex["name"] == "jj-kata"
    assert codex["skills"] == "./skills/"
    assert codex["version"] == claude["version"] == antigravity["version"]
    assert "start, claim, refresh, integrate, and drop" in codex["description"]
    assert "Kanban" in codex["description"]


def test_plugin_keeps_both_python_skills_and_worktree_bridges() -> None:
    expected = [
        ROOT / "scripts/jj-kata",
        ROOT / "hooks/worktree_create.py",
        ROOT / "hooks/worktree_remove.py",
    ]
    for command in expected:
        assert command.is_file() and os.access(command, os.X_OK)
        assert command.read_text().startswith("#!/usr/bin/env python3\n")

    assert (ROOT / "skills/kanban/SKILL.md").is_file()
    assert (ROOT / "skills/kata/SKILL.md").is_file()
    assert (ROOT / "pyproject.toml").is_file()


def test_every_shipped_executable_has_help() -> None:
    commands = [
        [ROOT / "scripts/jj-kata"],
        *[
            [ROOT / "scripts/jj-kata", command]
            for command in ("start", "claim", "refresh", "integrate", "drop")
        ],
        [ROOT / "scripts/jj-kata", "kanban"],
        *[
            [ROOT / "scripts/jj-kata", "kanban", command]
            for command in ("board", "ready", "blocked", "graph", "needs", "check")
        ],
        [ROOT / "hooks/worktree_create.py"],
        [ROOT / "hooks/worktree_remove.py"],
    ]
    for command in commands:
        result = subprocess.run(
            [*map(str, command), "--help"], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("usage:")


def test_superseded_generic_components_remain_absent() -> None:
    assert not (ROOT / "hooks.json").exists()
    assert not (ROOT / "hooks/hooks.json").exists()
    assert not (ROOT / "skills/setup").exists()
    assert not (ROOT / "skills/handoff").exists()
    executable_sources = [ROOT / name for name in ("src", "skills", "hooks", "tests")]
    assert not [
        path for source in executable_sources for path in source.rglob("*.fish")
    ]
    assert not [path for source in executable_sources for path in source.rglob("*.pl")]


def test_readme_draws_the_sensei_boundary() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "general Jujutsu" in readme and "foundation" in readme
    assert "start`/`claim` → `refresh` → `integrate` → `drop`" in readme
    assert "/PLUGIN/scripts/jj-kata" in readme
