from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_manifests_are_consistent() -> None:
    codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    antigravity = json.loads((ROOT / "plugin.json").read_text())

    assert codex["name"] == "jj-kata"
    assert codex["skills"] == "./skills/"
    assert codex["interface"]["displayName"] == "jj-kata"
    assert claude["displayName"] == antigravity["displayName"] == "jj-kata"
    assert codex["version"] == claude["version"] == antigravity["version"]

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    scripts = project["project"]["scripts"]
    assert scripts["kata"] == scripts["jj-kata"] == "jj_kata.cli:main"


def test_example_configs_remain_equivalent() -> None:
    canonical = (ROOT / "kata.example.toml").read_text().splitlines()
    compatibility = (ROOT / "jjkata.example.toml").read_text().splitlines()

    assert canonical[1:] == compatibility[1:]


def test_plugin_keeps_both_python_skills_and_worktree_bridges() -> None:
    expected = [
        ROOT / "scripts/kata",
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
    launchers = [ROOT / "scripts/kata", ROOT / "scripts/jj-kata"]
    commands = [
        *[[launcher] for launcher in launchers],
        *[
            [launcher, command]
            for launcher in launchers
            for command in ("start", "claim", "refresh", "integrate", "drop")
        ],
        *[[launcher, "kanban"] for launcher in launchers],
        *[
            [launcher, "kanban", command]
            for launcher in launchers
            for command in (
                "board",
                "ready",
                "blocked",
                "order",
                "graph",
                "needs",
                "check",
            )
        ],
        [ROOT / "hooks/worktree_create.py"],
        [ROOT / "hooks/worktree_remove.py"],
    ]
    for command in commands:
        result = subprocess.run(
            [*map(str, command), "--help"], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("usage: kata") or result.stdout.startswith(
            "usage: worktree_"
        )


def test_kata_skill_keeps_feature_work_out_of_default() -> None:
    guidance = " ".join((ROOT / "skills/kata/SKILL.md").read_text().split())

    assert "Do not do feature work in `default`" in guidance
    assert "even when only one agent is currently active" in guidance


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


def test_claude_project_hook_example_registers_only_worktree_events() -> None:
    example = json.loads((ROOT / "hooks/claude-project-hooks.example.json").read_text())

    assert set(example["hooks"]) == {"WorktreeCreate", "WorktreeRemove"}
    commands = [event[0]["hooks"][0]["command"] for event in example["hooks"].values()]
    assert commands == [
        '"/ABSOLUTE/PATH/TO/jj-kata/hooks/worktree_create.py"',
        '"/ABSOLUTE/PATH/TO/jj-kata/hooks/worktree_remove.py"',
    ]
