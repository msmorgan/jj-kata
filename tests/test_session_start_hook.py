from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "session_start.py"
PLUGIN_ROOT_VARIABLES = ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT")
TEST_CONFIG_HOME = Path(os.environ["XDG_CONFIG_HOME"])


def environment(**overrides: str) -> dict[str, str]:
    return {
        **os.environ,
        "NO_COLOR": "1",
        "XDG_CONFIG_HOME": str(TEST_CONFIG_HOME),
        **overrides,
    }


def jj(cwd: Path, *args: str) -> None:
    process = subprocess.run(
        ["jj", "--no-pager", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        env=environment(),
        check=False,
    )
    assert not process.returncode, process.stderr


def kata_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    jj(repo, "git", "init")
    (repo / "kata.toml").write_text('[items]\ndriver = "kanban"\n')
    return repo


def run_hook(
    payload: dict[str, object], *, command: list[str] | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command or ["python3", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=environment(**env),
        check=False,
    )


def test_claude_session_start_emits_plain_orientation(tmp_path: Path) -> None:
    repo = kata_repo(tmp_path)

    result = run_hook({"hook_event_name": "SessionStart", "cwd": str(repo)})

    assert result.returncode == 0
    assert result.stdout.startswith("jj-kata: default (coordinator)")
    assert "Load the `kata` skill" in result.stdout


def test_claude_session_start_in_a_feature_workspace_names_it(tmp_path: Path) -> None:
    repo = kata_repo(tmp_path)
    jj(repo, "workspace", "add", str(tmp_path / "alpha"))

    result = run_hook(
        {"hook_event_name": "SessionStart", "cwd": str(tmp_path / "alpha")}
    )

    assert result.returncode == 0
    assert result.stdout.startswith("jj-kata: alpha (feature workspace)")


def test_antigravity_first_invocation_injects_ephemeral_orientation(
    tmp_path: Path,
) -> None:
    repo = kata_repo(tmp_path)

    result = run_hook({"invocationNum": 0, "workspacePaths": [str(repo)]})

    assert result.returncode == 0
    message = json.loads(result.stdout)["injectSteps"][0]["ephemeralMessage"]
    assert message.startswith("jj-kata: default (coordinator)")


def test_antigravity_later_invocation_does_not_repeat_orientation(
    tmp_path: Path,
) -> None:
    repo = kata_repo(tmp_path)

    result = run_hook({"invocationNum": 1, "workspacePaths": [str(repo)]})

    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_antigravity_outside_a_kata_repository_returns_an_empty_response(
    tmp_path: Path,
) -> None:
    result = run_hook({"invocationNum": 0, "workspacePaths": [str(tmp_path)]})

    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_a_non_kata_repository_stays_silent(tmp_path: Path) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    jj(repo, "git", "init")

    result = run_hook({"hook_event_name": "SessionStart", "cwd": str(repo)})

    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    "payload", ["", "not json", "[]", "null"], ids=["empty", "text", "array", "null"]
)
def test_an_unusable_payload_never_fails_the_session(
    tmp_path: Path, payload: str
) -> None:
    """Hosts differ in what they send, and a hook that exits non-zero at session
    start is worse than one that says nothing."""
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment(),
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_a_missing_jj_never_fails_the_session(tmp_path: Path) -> None:
    repo = kata_repo(tmp_path)

    # Name the interpreter absolutely so emptying PATH hides jj alone.
    result = run_hook(
        {"hook_event_name": "SessionStart", "cwd": str(repo)},
        command=[sys.executable, str(HOOK)],
        PATH="/nonexistent",
    )

    assert result.returncode == 0
    assert result.stdout == ""


def hook_manifest_commands() -> list[str]:
    manifest = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    commands = [
        hook["command"]
        for entries in manifest["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
    ]
    assert commands, manifest
    return sorted(set(commands))


@pytest.mark.parametrize("command", hook_manifest_commands())
@pytest.mark.parametrize("plugin_root", PLUGIN_ROOT_VARIABLES)
def test_every_manifest_command_resolves_for_every_host(
    tmp_path: Path, plugin_root: str, command: str
) -> None:
    """Codex exports PLUGIN_ROOT and Claude exports CLAUDE_PLUGIN_ROOT. A command
    naming only one of them expands to an absolute path under `/`, and the hook
    silently never runs."""
    repo = kata_repo(tmp_path)
    without_roots = {
        name: value
        for name, value in environment().items()
        if name not in PLUGIN_ROOT_VARIABLES
    }

    result = subprocess.run(
        ["bash", "-c", command],
        input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(repo)}),
        capture_output=True,
        text=True,
        env={**without_roots, plugin_root: str(ROOT)},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("jj-kata: default (coordinator)")


def test_a_manifest_command_survives_a_plugin_root_containing_spaces(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "plugin cache" / "jj-kata"
    (installed / "hooks").mkdir(parents=True)
    (installed / "hooks" / "session_start.py").write_bytes(HOOK.read_bytes())
    (installed / "src").symlink_to(ROOT / "src")
    repo = kata_repo(tmp_path)

    result = subprocess.run(
        ["bash", "-c", hook_manifest_commands()[0]],
        input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(repo)}),
        capture_output=True,
        text=True,
        env=environment(CLAUDE_PLUGIN_ROOT=str(installed)),
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("jj-kata: default (coordinator)")


def test_antigravity_manifest_targets_the_shared_hook_script() -> None:
    manifest = json.loads((ROOT / "hooks.json").read_text())
    entries = manifest["jj-kata-orientation"]["PreInvocation"]

    assert [entry["type"] for entry in entries] == ["command"]
    # Antigravity runs hook commands from the plugin root, so the path is relative.
    relative = entries[0]["command"].removeprefix("python3 ./")
    assert relative != entries[0]["command"]
    assert (ROOT / relative).resolve() == HOOK.resolve()


def test_hook_manifests_register_only_session_orientation() -> None:
    """The worktree bridges replace native worktree creation, so they stay
    repository opt-in rather than joining a plugin manifest."""
    host = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    antigravity = json.loads((ROOT / "hooks.json").read_text())

    assert set(host["hooks"]) == {"SessionStart"}
    assert set(antigravity) == {"jj-kata-orientation"}
    assert set(antigravity["jj-kata-orientation"]) == {"PreInvocation"}
    registered = [
        *hook_manifest_commands(),
        *[
            entry["command"]
            for entries in antigravity.values()
            for entry in entries["PreInvocation"]
        ],
    ]
    assert not [command for command in registered if "worktree" in command]


def test_hook_script_is_executable() -> None:
    assert os.access(HOOK, os.X_OK)
