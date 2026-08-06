import json
import os
import re
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
    # The executables ship inside the skill that documents them, and NOWHERE
    # else — the skill tells an agent to run them relative to its own directory,
    # so a second copy (a bin/ shim, a PATH entry) is one more thing to go stale.
    for name in ("workflow", "conflicts"):
        script = ROOT / "skills/jj-workflow/scripts" / name
        assert script.is_file() and os.access(script, os.X_OK)
    assert not (ROOT / "bin").exists()


def test_skill_routes_commands_by_its_own_directory():
    skill = (ROOT / "skills/jj-workflow/SKILL.md").read_text()

    assert "this skill's own directory" in skill
    assert "scripts/workflow" in skill
    assert "scripts/conflicts" in skill


def test_sibling_skills_reach_the_toolkit_by_a_path_that_resolves():
    # A sibling skill names the toolkit the same way the toolkit's own skill
    # does: relative to the skill directory it is written in. Cheap to get
    # subtly wrong, and an agent following a broken path has nothing to fall
    # back on now that the command is not on PATH.
    checked = 0
    for skill_md in (ROOT / "skills").glob("*/SKILL.md"):
        for rel in re.findall(r"`(\.\./[\w./-]+)`", skill_md.read_text()):
            assert (skill_md.parent / rel).resolve().exists(), f"{skill_md}: {rel}"
            checked += 1
    assert checked, "no cross-skill relative paths found — did the idiom change?"


def test_guard_hook_only_decides_never_rewrites():
    # Command discovery must not depend on a hook firing: a hook that is
    # untrusted, unmatched, or simply not supported by the host is invisible,
    # and the toolkit would silently vanish. So the guard allows or blocks and
    # rewrites nothing.
    hook = (ROOT / "skills/jj-workflow/scripts/hooks/jj_guard.fish").read_text()

    assert "updatedInput" not in hook
    assert "export PATH" not in hook
    assert "JJ_WORKFLOW_HOST" not in hook


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
