import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_manifests_describe_the_kanban_only_plugin():
    codex = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    claude = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())
    antigravity = json.loads((ROOT / "plugin.json").read_text())

    assert codex["name"] == "jj-workflow"
    assert codex["skills"] == "./skills/"
    assert codex["version"] == claude["version"] == antigravity["version"]
    assert "Kanban" in codex["description"]
    assert (ROOT / "skills/kanban/SKILL.md").is_file()
    command = ROOT / "skills/kanban/scripts/kanban"
    assert command.is_file() and os.access(command, os.X_OK)


def test_superseded_components_are_absent():
    assert not (ROOT / "hooks.json").exists()
    assert not (ROOT / "hooks").exists()
    assert not (ROOT / "skills/jj-workflow").exists()
    assert not (ROOT / "skills/setup").exists()
    assert not (ROOT / "skills/handoff").exists()


def test_readme_points_superseded_features_to_jj_sensei():
    readme = (ROOT / "README.md").read_text()

    assert "moved to [jj-sensei]" in readme
    assert "/PLUGIN/skills/kanban/scripts/kanban" in readme
