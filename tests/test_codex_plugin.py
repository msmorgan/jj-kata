import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TODO_GRAPH = ROOT / "skills/jj-workflow/scripts/lib/todo_graph.pl"


def test_codex_manifest_exposes_plugin_components():
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())

    assert manifest["name"] == "jj-workflow"
    assert manifest["skills"] == "./skills/"
    assert manifest["version"] == json.loads(
        (ROOT / ".claude-plugin/plugin.json").read_text()
    )["version"]
    assert (ROOT / "skills/jj-workflow/SKILL.md").is_file()
    assert (ROOT / "skills/setup/SKILL.md").is_file()
    assert (ROOT / "skills/handoff/SKILL.md").is_file()
    assert (ROOT / "bin/workflow").resolve() == ROOT / "skills/jj-workflow/scripts/workflow"
    assert (ROOT / "bin/conflicts").resolve() == ROOT / "skills/jj-workflow/scripts/conflicts"


def test_todo_graph_treats_bugs_as_ordered_triage(tmp_path):
    tickets = tmp_path / "tickets"
    (tickets / "bugs").mkdir(parents=True)
    (tickets / "planned").mkdir()
    (tickets / "bugs/core-bug.md").write_text("---\nneeds: []\n---\n")
    (tickets / "planned/core-feature.md").write_text("---\nneeds: []\n---\n")
    census = tickets / "census.md"
    census.write_text("")

    result = subprocess.run(
        ["perl", str(TODO_GRAPH), "ready"],
        env={**os.environ, "TODO_ROOT": str(tickets), "TODO_CENSUS": str(census)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "core-bug  (bugs)",
        "core-feature  (planned)",
    ]


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


def test_status_hook_is_registered_unmatched_on_both_events():
    all_hooks = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]
    expected = (
        'fish "${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}'
        '/skills/jj-workflow/scripts/hooks/jj_status.fish"'
    )

    # PostToolBatch keeps the line current; SessionStart is where an agent knows
    # least. One script serves both and branches on hook_event_name.
    for event in ("PostToolBatch", "SessionStart"):
        hooks = all_hooks[event]
        commands = [hook["command"] for group in hooks for hook in group["hooks"]]
        assert commands == [expected], event
        # No matcher on either: PostToolBatch describes a whole batch rather than
        # one tool, and every SessionStart source (startup/resume/clear/compact/
        # fork) is a moment the line is worth having.
        assert all("matcher" not in group for group in hooks), event

    assert (ROOT / "skills/jj-workflow/scripts/hooks/jj_status.fish").is_file()
