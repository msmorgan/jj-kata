from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from jj_kata.orientation import orient, render

TEST_CONFIG_HOME = Path(os.environ["XDG_CONFIG_HOME"])
CURRENT_BOUNDARIES = [
    ('revset-aliases."other_workspaces()"', "working_copies() ~ @"),
    ('revset-aliases."not_default()"', "@ ~ default@"),
    (
        'revset-aliases."only_if(condition, revisions)"',
        "revisions & descendants(ancestors(condition))",
    ),
    (
        'revset-aliases."immutable_heads()"',
        "builtin_immutable_heads() | only_if(not_default(), other_workspaces())",
    ),
]
LEGACY_BOUNDARIES = [
    ('revset-aliases."all_if_any(rev)"', "descendants(ancestors(rev))"),
    (
        'revset-aliases."immutable_heads()"',
        (
            "builtin_immutable_heads() | ((working_copies() ~ @) & "
            "all_if_any(default@ ~ @))"
        ),
    ),
]


@pytest.fixture(autouse=True)
def _isolated_jj_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(TEST_CONFIG_HOME))
    monkeypatch.setenv("NO_COLOR", "1")
    # jj honors git's excludes, including core.excludesFile from the developer's
    # global config. A machine that ignores .workspaces globally cannot otherwise
    # produce the unignored state these tests assert on.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def jj(cwd: Path, *args: str) -> str:
    process = subprocess.run(
        ["jj", "--no-pager", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert not process.returncode, process.stderr
    return process.stdout


def init_repo(tmp_path: Path, *, config: str | None = "", name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    jj(repo, "git", "init")
    if config is not None:
        (repo / "kata.toml").write_text(config)
    return repo


def install_boundaries(repo: Path, aliases: list[tuple[str, str]]) -> None:
    for key, value in aliases:
        jj(repo, "config", "set", "--repo", key, value)


def test_a_jj_repository_without_kata_config_is_not_a_kata_project(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path, config=None)

    assert orient(repo) is None


def test_a_kata_config_outside_jj_is_not_a_kata_project(tmp_path: Path) -> None:
    """Kata coordinates jj workspaces. A kata.toml in a directory jj has never
    seen describes nothing this hook can orient an agent inside."""
    (tmp_path / "kata.toml").write_text('[items]\ndriver = "kanban"\n')

    assert orient(tmp_path) is None


@pytest.mark.parametrize("name", ["kata.toml", "jjkata.toml"])
def test_either_config_name_marks_a_kata_project(tmp_path: Path, name: str) -> None:
    repo = init_repo(tmp_path, config=None)
    (repo / name).write_text("")

    orientation = orient(repo)

    assert orientation is not None
    assert orientation.on_default
    assert orientation.workspace == "default"


def test_default_workspace_orients_as_the_coordinator(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)

    text = render(orient(repo))

    assert text.startswith("jj-kata: default (coordinator)")
    assert "unless specifically instructed otherwise" in text.lower()
    assert "Load the `kata` skill" in text


def test_feature_workspace_names_itself_and_its_siblings(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    jj(repo, "workspace", "add", str(tmp_path / "alpha"))
    jj(repo, "workspace", "add", str(tmp_path / "beta"))

    orientation = orient(tmp_path / "beta")

    assert orientation is not None
    assert orientation.workspace == "beta"
    assert not orientation.on_default
    assert orientation.default_root == repo.resolve()
    assert orientation.workspaces == ("default", "alpha", "beta")
    text = render(orientation)
    assert text.startswith("jj-kata: beta (feature workspace)")
    assert "live: default, alpha, beta" in text
    assert "never base work on another live feature's ancestry" in text


def test_a_workspace_outside_the_repository_tree_still_finds_its_default(
    tmp_path: Path,
) -> None:
    """A workspace_dir may point anywhere, so the config cannot be found by walking
    up from the workspace. jj resolves the default root regardless of where the
    feature workspace was placed."""
    repo = init_repo(tmp_path / "nested" / "deeper")
    elsewhere = tmp_path / "far" / "away" / "gamma"
    elsewhere.parent.mkdir(parents=True)
    jj(repo, "workspace", "add", str(elsewhere))

    orientation = orient(elsewhere)

    assert orientation is not None
    assert orientation.workspace == "gamma"
    assert orientation.default_root == repo.resolve()


def test_a_nested_directory_orients_as_its_workspace(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)

    orientation = orient(nested)

    assert orientation is not None
    assert orientation.on_default


def test_a_lone_default_workspace_lists_no_siblings(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)

    assert "live:" not in render(orient(repo))


def test_missing_boundaries_are_warned_about(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)

    orientation = orient(repo)

    assert orientation is not None
    assert not orientation.boundaries
    assert "no jj-sensei workspace boundaries" in render(orientation)


@pytest.mark.parametrize(
    ("aliases", "label"),
    [(CURRENT_BOUNDARIES, "current"), (LEGACY_BOUNDARIES, "legacy")],
    ids=["current", "legacy"],
)
def test_installed_boundaries_raise_no_warning(
    tmp_path: Path, aliases: list[tuple[str, str]], label: str
) -> None:
    """Lifecycle accepts both alias generations, so orientation must not warn about
    a guard Kata is willing to run under."""
    repo = init_repo(tmp_path)
    install_boundaries(repo, aliases)

    orientation = orient(repo)

    assert orientation is not None
    assert orientation.boundaries
    assert "boundaries" not in render(orientation)


def test_item_driver_and_shared_visibility_are_reported(tmp_path: Path) -> None:
    repo = init_repo(
        tmp_path,
        config='[items]\ndriver = ["python3", "items.py"]\nvisibility = "shared"\n',
    )

    assert "items: python3 items.py (shared claims)" in render(orient(repo))


def test_a_repository_with_no_item_driver_reports_none(tmp_path: Path) -> None:
    repo = init_repo(tmp_path, config='workspace_dir = ".workspaces"\n')

    assert "items: none" in render(orient(repo))


def test_an_unreadable_config_is_never_reported_as_no_driver(tmp_path: Path) -> None:
    """Kata refuses two config files outright. Orientation still runs, but saying
    'items: none' would describe a configuration nobody wrote."""
    repo = init_repo(tmp_path, config='[items]\ndriver = "kanban"\n')
    (repo / "jjkata.toml").write_text('[items]\ndriver = "kanban"\n')

    assert "items: unreadable" in render(orient(repo))


def snapshot(repo: Path) -> None:
    jj(repo, "st")


def test_an_unignored_workspace_directory_is_reported(tmp_path: Path) -> None:
    """Kata writes an ignore file when it creates the base, but declines to replace
    one already there, so a repository can end up snapshotting workspace clutter
    onto the coordinator's line."""
    repo = init_repo(tmp_path)
    (repo / ".workspaces").mkdir()
    (repo / ".workspaces" / "stray.txt").write_text("clutter\n")
    snapshot(repo)

    orientation = orient(repo)

    assert orientation is not None
    assert orientation.tracked == (".workspaces/stray.txt",)
    text = render(orientation)
    assert "The workspace directory is not ignored" in text
    assert "`.workspaces/stray.txt` is tracked" in text
    assert "Ignore `.workspaces/`" in text


def test_an_ignored_workspace_directory_raises_no_warning(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / ".workspaces").mkdir()
    (repo / ".workspaces" / ".gitignore").write_text("*\n")
    (repo / ".workspaces" / "stray.txt").write_text("clutter\n")
    snapshot(repo)

    orientation = orient(repo)

    assert orientation is not None
    assert orientation.tracked == ()
    assert "not ignored" not in render(orientation)


def test_a_globally_ignored_workspace_directory_raises_no_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ignore rule outside the repository satisfies the check as fully as one
    inside it, which is how this plugin's own author works."""
    excludes = tmp_path / "global-ignore"
    excludes.write_text(".workspaces\n")
    config = tmp_path / "gitconfig"
    config.write_text(f"[core]\n\texcludesFile = {excludes}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    repo = init_repo(tmp_path)
    (repo / ".workspaces").mkdir()
    (repo / ".workspaces" / "stray.txt").write_text("clutter\n")
    snapshot(repo)

    orientation = orient(repo)

    assert orientation is not None
    assert orientation.tracked == ()


def test_a_workspace_directory_outside_the_repository_needs_no_ignore(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "stray.txt").write_text("clutter\n")
    repo = init_repo(tmp_path, config=f'workspace_dir = "{outside}"\n')
    snapshot(repo)

    orientation = orient(repo)

    assert orientation is not None
    assert orientation.workspace_dir == ""
    assert orientation.tracked == ()


def test_the_configured_workspace_directory_is_the_one_checked(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path, config='workspace_dir = ".ws"\n')
    (repo / ".ws").mkdir()
    (repo / ".ws" / "stray.txt").write_text("clutter\n")
    (repo / ".workspaces").mkdir()
    (repo / ".workspaces" / "elsewhere.txt").write_text("unrelated\n")
    snapshot(repo)

    orientation = orient(repo)

    assert orientation is not None
    assert orientation.tracked == (".ws/stray.txt",)
    assert "Ignore `.ws/`" in render(orientation)


def test_many_tracked_paths_are_summarized(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / ".workspaces").mkdir()
    for index in range(5):
        (repo / ".workspaces" / f"stray{index}.txt").write_text("clutter\n")
    snapshot(repo)

    text = render(orient(repo))

    assert len(orient(repo).tracked) == 5
    assert "and 2 more are tracked" in text


def test_orientation_leaves_the_repository_untouched(tmp_path: Path) -> None:
    """The probe runs before the agent's first turn, alongside whatever state the
    last session left. It must not snapshot, update, or record an operation."""
    repo = init_repo(tmp_path)
    (repo / "uncommitted.txt").write_text("work in progress\n")
    # Read the state to protect without disturbing it: an ordinary jj command
    # snapshots the working copy, which is the very thing under test.
    quiet = ["--no-graph", "--ignore-working-copy"]
    operation = ["op", "log", "-n", "1", "-T", "id", *quiet]
    working_copy = ["log", "-r", "@", "-T", "commit_id", *quiet]
    before = (jj(repo, *operation), jj(repo, *working_copy))

    assert orient(repo) is not None

    assert (jj(repo, *operation), jj(repo, *working_copy)) == before
