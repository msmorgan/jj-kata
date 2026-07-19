import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_codex_manifest_exposes_plugin_components():
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())

    assert manifest["name"] == "jj-workflow"
    assert manifest["skills"] == "./skills/"
    assert manifest["version"] == json.loads(
        (ROOT / ".claude-plugin/plugin.json").read_text()
    )["version"]
    assert (ROOT / "skills/jj-workflow/SKILL.md").is_file()
    assert (ROOT / "skills/setup/SKILL.md").is_file()


def test_shared_hook_uses_portable_plugin_root():
    hooks = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"][
        "PreToolUse"
    ]
    commands = [
        hook["command"]
        for group in hooks
        for hook in group["hooks"]
    ]

    assert {group["matcher"] for group in hooks} == {"Bash", "run_command"}
    assert all("PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}" in command for command in commands)
