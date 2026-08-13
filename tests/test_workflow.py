from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from jj_kata.errors import KataError
from jj_kata.jj import Result
from jj_kata.lifecycle import Lifecycle

ROOT = Path(__file__).resolve().parent.parent
KATA = ROOT / "scripts" / "kata"
LEGACY_KATA = ROOT / "scripts" / "jj-kata"
WORKTREE_CREATE = ROOT / "hooks" / "worktree_create.py"
WORKTREE_REMOVE = ROOT / "hooks" / "worktree_remove.py"
TEST_CONFIG_HOME = Path("/tmp") / f"jj-kata-tests-{os.getpid()}"


def run(
    cwd: Path,
    *args: str,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        [*args],
        cwd=cwd,
        text=True,
        input=input_text,
        capture_output=True,
        env={
            **os.environ,
            "NO_COLOR": "1",
            "JJ_KATA_LOCK_TIMEOUT": "5",
            "XDG_CONFIG_HOME": str(TEST_CONFIG_HOME),
        },
        check=False,
    )
    if check and process.returncode:
        raise AssertionError(
            f"command failed ({process.returncode}): {' '.join(args)}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return process


def jj(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(cwd, "jj", "--no-pager", *args, check=check)


def workflow(
    cwd: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return run(cwd, str(KATA), *args, check=check)


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myproj"
    repo.mkdir(parents=True)
    jj(repo, "git", "init", "--colocate")
    jj(
        repo,
        "config",
        "set",
        "--repo",
        'revset-aliases."all_if_any(rev)"',
        "descendants(ancestors(rev))",
    )
    jj(
        repo,
        "config",
        "set",
        "--repo",
        'revset-aliases."immutable_heads()"',
        "builtin_immutable_heads() | ((working_copies() ~ @) & "
        "all_if_any(default@ ~ @))",
    )
    (repo / ".gitignore").write_text("*.tmp\n")
    (repo / "base.txt").write_text("base\n")
    jj(repo, "commit", "-m", "base")
    return repo


def test_lifecycle_requires_sensei_workspace_boundaries(tmp_path: Path) -> None:
    repo = tmp_path / "unguarded"
    repo.mkdir()
    jj(repo, "git", "init", "--colocate")
    (repo / "base.txt").write_text("base\n")
    jj(repo, "commit", "-m", "base")

    result = workflow(repo, "start", "unsafe", check=False)

    assert result.returncode == 2
    assert "install jj-sensei from msmorgan/marketplace" in result.stderr
    assert not (repo / ".workspaces/unsafe").exists()


@pytest.mark.parametrize(
    ("launcher", "config_name"),
    [(KATA, "kata.toml"), (LEGACY_KATA, "jjkata.toml")],
)
def test_command_and_config_names_remain_compatible(
    tmp_path: Path, launcher: Path, config_name: str
) -> None:
    repo = init_repo(tmp_path)
    (repo / config_name).write_text('workspace_dir = ".kata-workspaces"\n')

    result = run(repo, str(launcher), "start", "compatible")

    workspace = repo / ".kata-workspaces/compatible"
    assert Path(result.stdout.strip()) == workspace
    assert workspace.is_dir()


def enable_kanban(repo: Path) -> None:
    path = repo / "jjkata.toml"
    contents = path.read_text() if path.is_file() else ""
    if "[items]" not in contents:
        path.write_text(contents + '\n[items]\ndriver = "kanban"\n')


def add_ticket(repo: Path, slug: str, column: str = "planned") -> None:
    enable_kanban(repo)
    directory = repo / "docs" / "tickets" / column
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{slug}.md").write_text(f"# {slug}\n")
    jj(repo, "commit", "-m", f"tickets: add {slug}")


def test_ad_hoc_start_integrate_and_drop(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    workspace = repo / ".workspaces" / "feature-a"

    result = workflow(repo, "start", "feature-a")
    assert Path(result.stdout.strip()) == workspace
    assert workspace.is_dir()

    (workspace / "feature.txt").write_text("hello\n")
    jj(workspace, "commit", "-m", "feat: add feature")

    workflow(repo, "integrate", "feature-a")
    assert (repo / "feature.txt").read_text() == "hello\n"
    assert workspace.is_dir()
    assert not jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        'bookmarks(exact:"feature-a")',
        "-T",
        "change_id",
    ).stdout

    workflow(repo, "drop", "feature-a")
    assert not workspace.exists()
    assert "feature-a" not in jj(repo, "workspace", "list").stdout


def test_ticket_folders_do_not_implicitly_enable_kanban(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    ticket = repo / "docs/tickets/planned/unconfigured.md"
    ticket.parent.mkdir(parents=True)
    ticket.write_text("just a repository file\n")
    jj(repo, "commit", "-m", "docs: add an unrelated ticket-shaped file")

    result = workflow(repo, "claim", "unconfigured", check=False)

    assert result.returncode == 2
    assert "configure [items].driver" in result.stderr
    assert not (repo / ".workspaces/unconfigured").exists()


def test_ticket_claim_refresh_and_integrate(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "ticket-a")

    workflow(repo, "claim", "ticket-a")
    workspace = repo / ".workspaces" / "ticket-a"
    assert (workspace / "docs" / "tickets" / "wip" / "ticket-a.md").is_file()
    assert (repo / "docs" / "tickets" / "planned" / "ticket-a.md").is_file()
    assert not (repo / "docs" / "tickets" / "wip" / "ticket-a.md").exists()

    (repo / "trunk.txt").write_text("trunk moved\n")
    jj(repo, "commit", "-m", "trunk: move")
    (workspace / "feature.txt").write_text("feature\n")
    jj(workspace, "commit", "-m", "feat: ticket a")

    behind = workflow(repo, "integrate", "ticket-a", check=False)
    assert behind.returncode == 2
    assert "behind default" in behind.stderr

    workflow(workspace, "refresh")
    workflow(workspace, "integrate")

    assert (repo / "trunk.txt").is_file()
    assert (repo / "feature.txt").is_file()
    assert (repo / "docs" / "tickets" / "done" / "ticket-a.md").is_file()
    assert not (repo / "docs" / "tickets" / "wip" / "ticket-a.md").exists()
    descriptions = jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        "::default@",
        "-T",
        'description.first_line() ++ "\\n"',
    ).stdout
    assert "kata: claim ticket-a" in descriptions
    assert "kata: complete ticket-a" in descriptions


def test_shared_visibility_publishes_claim_through_an_anchor(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "jjkata.toml").write_text(
        '[items]\ndriver = "kanban"\nvisibility = "shared"\n'
    )
    jj(repo, "commit", "-m", "kata: configure shared visibility")
    add_ticket(repo, "ticket-a")

    workflow(repo, "claim", "ticket-a")

    workspace = repo / ".workspaces" / "ticket-a"
    assert (repo / "docs/tickets/wip/ticket-a.md").is_file()
    assert (workspace / "docs/tickets/wip/ticket-a.md").is_file()
    assert jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        'bookmarks(exact:"ticket-a")',
        "-T",
        "change_id",
    ).stdout.strip()


def test_bare_start_ignores_claim_visibility(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "jjkata.toml").write_text(
        '[items]\ndriver = "kanban"\nvisibility = "shared"\n'
    )

    workflow(repo, "start", "unticketed")
    workspace = repo / ".workspaces/unticketed"
    (workspace / "feature.txt").write_text("no ticket system required\n")
    jj(workspace, "commit", "-m", "feat: unticketed work")
    workflow(repo, "integrate", "unticketed")

    assert (repo / "feature.txt").is_file()
    assert not jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        'bookmarks(exact:"unticketed")',
        "-T",
        "change_id",
    ).stdout


def test_reconstructed_feature_tree_needs_no_hidden_claim_state(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "manual-ticket")
    workspace = repo / ".workspaces" / "manual-claim"
    workspace.parent.mkdir()
    jj(
        repo,
        "workspace",
        "add",
        str(workspace),
        "--name",
        "manual-claim",
        "-r",
        "default@-",
    )
    source = workspace / "docs/tickets/planned/manual-ticket.md"
    destination = workspace / "docs/tickets/wip/manual-ticket.md"
    destination.parent.mkdir(parents=True)
    source.replace(destination)
    jj(workspace, "commit", "-m", "reconstruct the intended claim tree")

    workflow(repo, "integrate", "manual-claim")

    assert (repo / "docs/tickets/done/manual-ticket.md").is_file()
    assert not (repo / ".jj/kata/claims/manual-claim.json").exists()


def test_kanban_folders_and_extension_are_repository_configuration(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "jjkata.toml").write_text(
        """[items]
driver = "kanban"

[kanban]
root = "tasks"
wip = "doing"
done = "finished"
patterns = ["*.task"]
"""
    )
    backlog = repo / "tasks/backlog"
    backlog.mkdir(parents=True)
    (backlog / "odd-job.task").write_text("an opaque work marker\n")
    jj(repo, "commit", "-m", "tasks: add odd job")

    workflow(repo, "claim", "odd-job")
    workspace = repo / ".workspaces/odd-job"

    assert (repo / "tasks/backlog/odd-job.task").is_file()
    assert (workspace / "tasks/doing/odd-job.task").is_file()
    workflow(repo, "integrate", "odd-job")
    assert (repo / "tasks/finished/odd-job.task").is_file()


def test_repository_script_can_own_items_and_kanban_commands(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    scripts = repo / "scripts"
    scripts.mkdir()
    driver = scripts / "items.py"
    driver.write_text(
        """#!/usr/bin/env python3
import json
import pathlib
import shutil
import subprocess
import sys

action = sys.argv[1]
root = pathlib.Path.cwd()
if action == "ready":
    print("external-ready")
    raise SystemExit(0)
payload = json.load(sys.stdin)
requested = payload["requested"]

def files(revision):
    result = subprocess.run(
        ["jj", "--no-pager", "file", "list", "-r", revision],
        text=True,
        capture_output=True,
        check=True,
    )
    return set(result.stdout.splitlines())

paths = []
if action == "probe":
    items = [item for item in requested if (root / "queue" / f"{item}.item").is_file()]
elif action == "claim":
    items = requested
    for item in items:
        source = root / "queue" / f"{item}.item"
        destination = root / "active" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, destination)
        paths.extend([f"queue/{source.name}", f"active/{source.name}"])
elif action == "owned":
    before = files(payload["context"]["base_revision"])
    after = files(payload["context"]["revision"])
    items = sorted(
        pathlib.PurePosixPath(path).stem
        for path in after - before
        if path.startswith("active/")
    )
elif action == "complete":
    items = requested
    for item in items:
        source = root / "active" / f"{item}.item"
        destination = root / "finished" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, destination)
        paths.extend([f"active/{source.name}", f"finished/{source.name}"])
else:
    raise SystemExit(f"unsupported action: {action}")
print(json.dumps({"items": items, "paths": paths}))
"""
    )
    driver.chmod(0o755)
    (repo / "jjkata.toml").write_text(
        '[items]\ndriver = "scripts/items.py"\n\n'
        '[kanban]\ncommand = "scripts/items.py"\n'
    )
    queue = repo / "queue"
    queue.mkdir()
    (queue / "ticket:42.item").write_text("opaque\n")
    jj(repo, "commit", "-m", "items: configure repository driver")

    workflow(repo, "claim", "ticket:42", "--name", "scripted")
    workspace = repo / ".workspaces/scripted"
    assert (workspace / "active/ticket:42.item").is_file()
    assert (repo / "queue/ticket:42.item").is_file()

    inspected = workflow(repo, "kanban", "ready")
    assert inspected.stdout == "external-ready\n"

    workflow(repo, "integrate", "scripted")
    assert (repo / "finished/ticket:42.item").is_file()


def test_claim_into_existing_workspace_completes_every_ticket(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "ticket-a")
    add_ticket(repo, "ticket-b")
    workflow(repo, "claim", "ticket-a")

    workflow(repo, "claim", "ticket-b", "--into", "ticket-a")
    workspace = repo / ".workspaces" / "ticket-a"
    assert (workspace / "docs/tickets/wip/ticket-a.md").is_file()
    assert (workspace / "docs/tickets/wip/ticket-b.md").is_file()
    (workspace / "feature.txt").write_text("both tickets\n")
    jj(workspace, "commit", "-m", "feat: both tickets")

    workflow(repo, "integrate", "ticket-a")

    assert (repo / "docs/tickets/done/ticket-a.md").is_file()
    assert (repo / "docs/tickets/done/ticket-b.md").is_file()
    description = jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        'description(glob:"kata: claim *")',
        "-T",
        "description",
    ).stdout
    assert description == "kata: claim ticket-a, ticket-b\n"


def test_kata_commit_descriptions_are_configurable(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "jjkata.toml").write_text(
        """[items]
driver = "kanban"

[messages]
claim = "take({workspace}): {items}"
complete = "finish({workspace}): {items}"
return = "return({workspace}): {items}"
"""
    )
    add_ticket(repo, "ticket-a")
    add_ticket(repo, "ticket-b")
    workflow(repo, "claim", "ticket-a")
    workflow(repo, "claim", "ticket-b", "--into", "ticket-a")
    workspace = repo / ".workspaces/ticket-a"
    (workspace / "feature.txt").write_text("done\n")
    jj(workspace, "commit", "-m", "feat: finish both tickets")

    workflow(repo, "integrate", "ticket-a")

    descriptions = jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        "::default@",
        "-T",
        'description.first_line() ++ "\\n"',
    ).stdout
    assert descriptions.count("take(ticket-a): ticket-a, ticket-b") == 1
    assert "finish(ticket-a): ticket-a, ticket-b" in descriptions

    add_ticket(repo, "ticket-c")
    workflow(repo, "claim", "ticket-c")
    ticket_c = repo / ".workspaces/ticket-c/docs/tickets/wip/ticket-c.md"
    ticket_c.write_text("# ticket-c\n\nreturned notes\n")
    workflow(repo, "drop", "ticket-c", "--return-items")

    assert (
        jj(repo, "log", "--no-graph", "-r", "default@-", "-T", "description").stdout
        == "return(ticket-c): ticket-c\n"
    )


def test_default_refresh_reorders_feature_before_integrate(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    workflow(repo, "start", "feature-a")
    workspace = repo / ".workspaces" / "feature-a"
    (repo / "trunk.txt").write_text("new trunk\n")
    jj(repo, "commit", "-m", "trunk: advance")
    (workspace / "feature.txt").write_text("feature\n")
    jj(workspace, "commit", "-m", "feat: work")

    workflow(repo, "refresh", "feature-a")
    workflow(repo, "integrate", "feature-a")

    assert (repo / "trunk.txt").is_file()
    assert (repo / "feature.txt").is_file()


def test_refresh_all_skips_a_missing_workspace_directory(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    workflow(repo, "start", "healthy")
    workflow(repo, "start", "missing")
    missing = repo / ".workspaces/missing"
    shutil.rmtree(missing)
    (repo / "trunk.txt").write_text("new trunk\n")
    jj(repo, "commit", "-m", "trunk: advance")

    result = workflow(repo, "refresh", "--all")

    assert result.returncode == 0
    assert "leaving stale workspace(s) untouched: missing" in result.stderr
    assert "refreshed 1 workspace(s)" in result.stderr
    assert not missing.exists()


def test_integrate_requires_closed_working_copy(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    workflow(repo, "start", "feature-a")
    workspace = repo / ".workspaces" / "feature-a"
    (workspace / "open.txt").write_text("still open\n")

    result = workflow(repo, "integrate", "feature-a", check=False)

    assert result.returncode == 69
    assert "still holds work" in result.stderr
    assert (workspace / "open.txt").is_file()
    assert not (repo / "open.txt").exists()


def test_drop_return_items_preserves_notes_in_origin_column(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "blocked-ticket")
    workflow(repo, "claim", "blocked-ticket")
    workspace = repo / ".workspaces" / "blocked-ticket"
    ticket = workspace / "docs" / "tickets" / "wip" / "blocked-ticket.md"
    ticket.write_text("# blocked-ticket\n\nBlocked on an upstream API.\n")

    workflow(repo, "drop", "blocked-ticket", "--return-items")

    restored = repo / "docs" / "tickets" / "planned" / "blocked-ticket.md"
    assert "Blocked on an upstream API" in restored.read_text()
    assert not workspace.exists()
    assert (
        jj(repo, "log", "--no-graph", "-r", "default@-", "-T", "description").stdout
        == "items: return blocked-ticket\n"
    )


def test_return_items_refuses_unrelated_work_before_moving_markers(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "blocked-ticket")
    workflow(repo, "claim", "blocked-ticket")
    workspace = repo / ".workspaces/blocked-ticket"
    ticket = workspace / "docs/tickets/wip/blocked-ticket.md"
    ticket.write_text("blocked notes\n")
    (workspace / "unrelated.txt").write_text("do not discard\n")

    result = workflow(repo, "drop", "blocked-ticket", "--return-items", check=False)

    assert result.returncode == 2
    assert ticket.read_text() == "blocked notes\n"
    assert not (workspace / "docs/tickets/planned/blocked-ticket.md").exists()
    assert (workspace / "unrelated.txt").is_file()


def test_plain_drop_refuses_unintegrated_work(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    workflow(repo, "start", "feature-a")
    workspace = repo / ".workspaces" / "feature-a"
    (workspace / "work.txt").write_text("keep me\n")

    result = workflow(repo, "drop", "feature-a", check=False)

    assert result.returncode == 2
    assert "un-integrated work" in result.stderr
    assert workspace.is_dir()
    assert (workspace / "work.txt").is_file()


def test_worktree_hooks_create_and_safely_remove_ad_hoc_workspace(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    payload = json.dumps({"cwd": str(repo), "name": "background-task"})

    created = run(repo, str(WORKTREE_CREATE), input_text=payload)
    workspace = repo / ".workspaces" / "background-task"
    assert Path(created.stdout.strip()) == workspace
    assert workspace.is_dir()

    removed = run(repo, str(WORKTREE_REMOVE), input_text=payload)
    assert removed.returncode == 0
    assert not workspace.exists()


def test_worktree_hooks_handle_malformed_input_without_tracebacks() -> None:
    created = run(ROOT, str(WORKTREE_CREATE), check=False, input_text="not json")
    removed = run(ROOT, str(WORKTREE_REMOVE), check=False, input_text="not json")

    assert created.returncode == 2
    assert "invalid worktree hook input" in created.stderr
    assert "Traceback" not in created.stderr
    assert removed.returncode == 0
    assert "invalid worktree hook input" in removed.stderr
    assert "Traceback" not in removed.stderr


def test_foreign_same_named_bookmark_is_never_treated_as_shared_anchor(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    workflow(repo, "start", "a")
    workflow(repo, "start", "b")
    a = repo / ".workspaces/a"
    b = repo / ".workspaces/b"
    (a / "a.txt").write_text("a\n")
    jj(a, "commit", "-m", "feat: a")
    (b / "b.txt").write_text("b\n")
    jj(b, "commit", "-m", "feat: b")
    jj(repo, "bookmark", "create", "a", "-r", "b@-")

    workflow(repo, "integrate", "a")
    workflow(repo, "drop", "a")

    assert (repo / "a.txt").is_file()
    assert not (repo / "b.txt").exists()
    assert jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        'bookmarks(exact:"a")',
        "-T",
        "change_id",
    ).stdout.strip()


def test_complete_shared_lifecycle_refreshes_integrates_and_drops(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "jjkata.toml").write_text(
        '[items]\ndriver = "kanban"\nvisibility = "shared"\n'
    )
    add_ticket(repo, "shared-ticket")
    workflow(repo, "claim", "shared-ticket")
    workspace = repo / ".workspaces/shared-ticket"
    (workspace / "feature.txt").write_text("feature\n")
    jj(workspace, "commit", "-m", "feat: shared work")
    (repo / "coordinator.txt").write_text("coordinator\n")
    jj(repo, "commit", "-m", "trunk: advance")

    workflow(repo, "refresh", "shared-ticket")
    workflow(repo, "integrate", "shared-ticket")
    workflow(repo, "drop", "shared-ticket")

    assert (repo / "feature.txt").is_file()
    assert (repo / "coordinator.txt").is_file()
    assert (repo / "docs/tickets/done/shared-ticket.md").is_file()
    assert not workspace.exists()
    assert not jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        'bookmarks(exact:"shared-ticket")',
        "-T",
        "change_id",
    ).stdout.strip()


def test_return_items_refuses_newer_default_ticket_edits(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "collision")
    workflow(repo, "claim", "collision")
    workspace = repo / ".workspaces/collision"
    wip = workspace / "docs/tickets/wip/collision.md"
    wip.write_text("feature notes\n")
    planned = repo / "docs/tickets/planned/collision.md"
    planned.write_text("new coordinator notes\n")
    jj(repo, "commit", "-m", "tickets: coordinator edits collision")

    result = workflow(repo, "drop", "collision", "--return-items", check=False)

    assert result.returncode == 2
    assert "without overwriting coordinator work" in result.stderr
    assert planned.read_text() == "new coordinator notes\n"
    assert wip.read_text() == "feature notes\n"
    assert workspace.is_dir()


def test_drop_reports_conflicts_it_leaves_on_the_default_line(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "jjkata.toml").write_text(
        '[items]\ndriver = "kanban"\nvisibility = "shared"\n'
    )
    jj(repo, "commit", "-m", "kata: configure shared visibility")
    add_ticket(repo, "tug")
    workflow(repo, "claim", "tug")
    (repo / "docs/tickets/wip/tug.md").write_text("coordinator rewrote this\n")
    jj(repo, "commit", "-m", "tickets: coordinator edits the wip card")

    result = workflow(repo, "drop", "tug", check=False)

    assert result.returncode == 69
    assert "left conflicts in" in result.stderr
    assert "harmony skill" in result.stderr


def test_shared_return_lands_beside_a_live_coordinator_change(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "jjkata.toml").write_text(
        '[items]\ndriver = "kanban"\nvisibility = "shared"\n'
    )
    jj(repo, "commit", "-m", "kata: configure shared visibility")
    add_ticket(repo, "guided-tour")
    (repo / "coordinator.txt").write_text("coordinator work\n")
    jj(repo, "describe", "-m", "docs: coordinator work in progress")
    coordinator = jj(repo, "log", "--no-graph", "-r", "@", "-T", "change_id").stdout

    workflow(repo, "claim", "guided-tour")
    ticket = repo / ".workspaces/guided-tour/docs/tickets/wip/guided-tour.md"
    ticket.write_text(ticket.read_text() + "blocked upstream\n")

    result = workflow(repo, "drop", "guided-tour", "--return-items")

    assert "returned its item edits" in result.stderr
    assert not jj(
        repo, "log", "--no-graph", "-r", "conflicts()", "-T", "change_id"
    ).stdout
    returned = repo / "docs/tickets/planned/guided-tour.md"
    assert "blocked upstream" in returned.read_text()
    assert not (repo / "docs/tickets/wip").exists()
    assert (
        jj(repo, "log", "--no-graph", "-r", "default@-", "-T", "description").stdout
        == "items: return guided-tour\n"
    )
    assert jj(repo, "log", "--no-graph", "-r", "@", "-T", "change_id").stdout == (
        coordinator
    )
    assert (
        jj(repo, "log", "--no-graph", "-r", "@", "-T", "description").stdout
        == "docs: coordinator work in progress\n"
    )
    assert (repo / "coordinator.txt").is_file()


def test_return_apply_failure_restores_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "recoverable")
    workflow(repo, "claim", "recoverable")
    workspace = repo / ".workspaces/recoverable"
    wip = workspace / "docs/tickets/wip/recoverable.md"
    wip.write_text("recover me\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(TEST_CONFIG_HOME))
    lifecycle = Lifecycle(cwd=repo)

    def fail_apply(*args: object, **kwargs: object) -> bool:
        raise KataError("injected return failure", 2)

    monkeypatch.setattr(lifecycle, "_apply_paths", fail_apply)
    with pytest.raises(KataError, match="injected return failure"):
        lifecycle.drop("recoverable", return_items=True)

    assert workspace.is_dir()
    assert wip.read_text() == "recover me\n"
    assert (repo / "docs/tickets/planned/recoverable.md").is_file()


def test_drop_rechecks_workspace_state_immediately_before_destruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path)
    workflow(repo, "start", "racing")
    workspace = repo / ".workspaces/racing"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(TEST_CONFIG_HOME))
    lifecycle = Lifecycle(cwd=repo)
    original_bank = lifecycle.bank_workspaces

    def race_after_preflight() -> None:
        original_bank()
        (workspace / "late.txt").write_text("arrived during drop\n")

    monkeypatch.setattr(lifecycle, "bank_workspaces", race_after_preflight)
    with pytest.raises(KataError, match="changed after drop preflight"):
        lifecycle.drop("racing")

    assert workspace.is_dir()
    assert (workspace / "late.txt").is_file()


def test_or_start_falls_back_for_absent_board_and_missing_item(tmp_path: Path) -> None:
    absent = init_repo(tmp_path / "absent")
    (absent / "jjkata.toml").write_text('[items]\ndriver = "kanban"\n')
    jj(absent, "commit", "-m", "kata: configure optional board")
    workflow(absent, "claim", "background", "--or-start")
    assert (absent / ".workspaces/background").is_dir()

    missing = init_repo(tmp_path / "missing")
    add_ticket(missing, "some-other-item")
    workflow(missing, "claim", "background", "--or-start")
    assert (missing / ".workspaces/background").is_dir()


def test_or_start_refuses_ambiguous_item_and_broken_driver(tmp_path: Path) -> None:
    ambiguous = init_repo(tmp_path / "ambiguous")
    add_ticket(ambiguous, "same", "planned")
    duplicate = ambiguous / "docs/tickets/later/same.md"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text("duplicate\n")
    jj(ambiguous, "commit", "-m", "tickets: add ambiguous duplicate")
    result = workflow(ambiguous, "claim", "same", "--or-start", check=False)
    assert result.returncode == 2
    assert "ambiguous" in result.stderr
    assert not (ambiguous / ".workspaces/same").exists()

    broken = init_repo(tmp_path / "broken")
    (broken / "jjkata.toml").write_text('[items]\ndriver = "scripts/does-not-exist"\n')
    result = workflow(broken, "claim", "anything", "--or-start", check=False)
    assert result.returncode == 2
    assert "could not run item driver" in result.stderr
    assert "Traceback" not in result.stderr

    corrupt = init_repo(tmp_path / "corrupt")
    (corrupt / "jjkata.toml").write_text('[items]\ndriver = "kanban"\n')
    board_file = corrupt / "docs/tickets"
    board_file.parent.mkdir()
    board_file.write_text("not a directory\n")
    jj(corrupt, "commit", "-m", "kata: add corrupt board path")
    result = workflow(corrupt, "claim", "anything", "--or-start", check=False)
    assert result.returncode == 2
    assert "Kanban root is not a directory" in result.stderr
    assert not (corrupt / ".workspaces/anything").exists()


def test_legacy_config_is_a_hard_clean_break(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "jjworkflow.toml").write_text("[workflow]\n")

    result = workflow(repo, "start", "unsafe", check=False)

    assert result.returncode == 2
    assert "legacy jjworkflow.toml state" in result.stderr
    assert not (repo / ".workspaces/unsafe").exists()


def test_ambiguous_bulk_drop_flags_are_removed(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)

    result = workflow(repo, "drop", "--help")

    assert "--integrated" not in result.stdout
    assert "--dry-run" not in result.stdout


def test_empty_driver_paths_never_consume_unrelated_open_work(tmp_path: Path) -> None:
    driver_source = """#!/usr/bin/env python3
import json
import sys

action = sys.argv[1]
payload = json.load(sys.stdin)
if action == "owned":
    items = ["external"] if payload["context"]["visibility"] == "shared" else []
else:
    items = payload["requested"]
print(json.dumps({"items": items, "paths": []}))
"""

    feature_repo = init_repo(tmp_path / "feature")
    (feature_repo / "scripts").mkdir()
    feature_driver = feature_repo / "scripts/items.py"
    feature_driver.write_text(driver_source)
    feature_driver.chmod(0o755)
    (feature_repo / "jjkata.toml").write_text('[items]\ndriver = "scripts/items.py"\n')
    jj(feature_repo, "commit", "-m", "kata: configure external items")
    workflow(feature_repo, "start", "feature-empty")
    feature = feature_repo / ".workspaces/feature-empty"
    (feature / "unrelated.txt").write_text("still open\n")

    workflow(feature, "claim", "external")

    assert jj(feature, "diff", "--name-only").stdout.splitlines() == ["unrelated.txt"]
    assert not jj(
        feature,
        "log",
        "--no-graph",
        "-r",
        "@-",
        "-T",
        "description",
    ).stdout.startswith("kata: claim")

    shared_repo = init_repo(tmp_path / "shared")
    (shared_repo / "scripts").mkdir()
    shared_driver = shared_repo / "scripts/items.py"
    shared_driver.write_text(driver_source)
    shared_driver.chmod(0o755)
    (shared_repo / "jjkata.toml").write_text(
        '[items]\ndriver = "scripts/items.py"\nvisibility = "shared"\n'
    )
    jj(shared_repo, "commit", "-m", "kata: configure external shared items")
    (shared_repo / "unrelated.txt").write_text("still open\n")

    workflow(shared_repo, "claim", "external")

    assert jj(shared_repo, "diff", "--name-only").stdout.splitlines() == [
        "unrelated.txt"
    ]
    assert (
        jj(
            shared_repo,
            "log",
            "--no-graph",
            "-r",
            'bookmarks(exact:"external")',
            "-T",
            "description",
        ).stdout
        == "kata: claim external\n"
    )


def test_shared_driver_completion_failure_lands_nothing_and_can_retry(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    sentinel = tmp_path / "fail-complete"
    sentinel.write_text("fail\n")
    scripts = repo / "scripts"
    scripts.mkdir()
    driver = scripts / "items.py"
    driver.write_text(
        f"""#!/usr/bin/env python3
import json
import pathlib
import shutil
import subprocess
import sys

action = sys.argv[1]
root = pathlib.Path.cwd()
payload = json.load(sys.stdin)
requested = payload["requested"]

def files(revision):
    result = subprocess.run(
        ["jj", "--no-pager", "file", "list", "-r", revision],
        text=True, capture_output=True, check=True,
    )
    return set(result.stdout.splitlines())

paths = []
if action == "claim":
    items = requested
    for item in items:
        source = root / "queue" / f"{{item}}.item"
        destination = root / "active" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, destination)
        paths.extend([f"queue/{{source.name}}", f"active/{{source.name}}"])
elif action == "owned":
    before = files(payload["context"]["base_revision"])
    after = files(payload["context"]["revision"])
    items = sorted(
        pathlib.PurePosixPath(path).stem
        for path in after - before if path.startswith("active/")
    )
elif action == "complete":
    if pathlib.Path({str(sentinel)!r}).exists():
        print("injected completion failure", file=sys.stderr)
        raise SystemExit(23)
    items = requested
    for item in items:
        source = root / "active" / f"{{item}}.item"
        destination = root / "finished" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, destination)
        paths.extend([f"active/{{source.name}}", f"finished/{{source.name}}"])
elif action == "probe":
    items = requested
else:
    raise SystemExit(f"unsupported {{action}}")
print(json.dumps({{"items": items, "paths": paths}}))
"""
    )
    driver.chmod(0o755)
    (repo / "jjkata.toml").write_text(
        '[items]\ndriver = "scripts/items.py"\nvisibility = "shared"\n'
    )
    (repo / "queue").mkdir()
    (repo / "queue/work.item").write_text("work\n")
    jj(repo, "commit", "-m", "items: configure failing shared driver")
    workflow(repo, "claim", "work")
    workspace = repo / ".workspaces/work"
    (workspace / "feature.txt").write_text("feature\n")
    jj(workspace, "commit", "-m", "feat: shared work")

    failed = workflow(repo, "integrate", "work", check=False)

    assert failed.returncode == 2
    assert "injected completion failure" in failed.stderr
    assert not (repo / "feature.txt").exists()
    assert (repo / "active/work.item").is_file()
    assert workspace.is_dir()
    sentinel.unlink()

    workflow(repo, "integrate", "work")
    workflow(repo, "drop", "work")

    assert (repo / "feature.txt").is_file()
    assert (repo / "finished/work.item").is_file()
    assert not workspace.exists()


def test_refresh_conflict_stops_with_harmony_guidance(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "base.txt").write_text("default edit\n")
    workflow(repo, "start", "conflicted")
    workspace = repo / ".workspaces/conflicted"
    (workspace / "base.txt").write_text("feature edit\n")
    jj(workspace, "commit", "-m", "feat: conflicting edit")
    jj(repo, "commit", "-m", "trunk: conflicting edit")

    result = workflow(repo, "refresh", "conflicted", check=False)

    assert result.returncode == 69
    assert "harmony skill" in result.stderr
    assert workspace.is_dir()


def test_shared_refresh_conflict_stops_with_harmony_guidance(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "jjkata.toml").write_text(
        '[items]\ndriver = "kanban"\nvisibility = "shared"\n'
    )
    add_ticket(repo, "conflicted")
    workflow(repo, "claim", "conflicted")
    workspace = repo / ".workspaces/conflicted"
    (workspace / "base.txt").write_text("feature edit\n")
    jj(workspace, "commit", "-m", "feat: conflicting edit")
    (repo / "base.txt").write_text("default edit\n")
    jj(repo, "commit", "-m", "trunk: conflicting edit")

    result = workflow(repo, "refresh", "conflicted", check=False)

    assert result.returncode == 69
    assert "harmony skill" in result.stderr
    assert workspace.is_dir()


def test_postflight_reports_divergent_working_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(TEST_CONFIG_HOME))
    lifecycle = Lifecycle(cwd=repo)
    original_changes = lifecycle._changes

    def divergent(revset: str, cwd: Path | None = None) -> list[str]:
        if revset == "working_copies() & divergent()":
            return ["divergent-change"]
        return original_changes(revset, cwd)

    monkeypatch.setattr(lifecycle, "_changes", divergent)
    with pytest.raises(KataError) as failure:
        lifecycle.unstale_workspaces()

    assert failure.value.code == 69
    assert "harmony skill" in str(failure.value)


def test_postflight_reports_update_stale_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = init_repo(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(TEST_CONFIG_HOME))
    lifecycle = Lifecycle(cwd=repo)
    original_run = lifecycle.jj.run

    def fail_update(*args: str, **kwargs: object) -> Result:
        if args[:2] == ("workspace", "update-stale"):
            return Result("", "injected stale failure", 1)
        return original_run(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(lifecycle.jj, "run", fail_update)
    with pytest.raises(KataError) as failure:
        lifecycle.unstale_workspaces()

    assert failure.value.code == 69
    assert "stale workspace(s): default" in str(failure.value)


def test_lock_timeout_has_stable_exit_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name != "posix":
        pytest.skip("POSIX lifecycle lock")
    import fcntl

    repo = init_repo(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(TEST_CONFIG_HOME))
    monkeypatch.setenv("JJ_KATA_LOCK_TIMEOUT", "0")
    lifecycle = Lifecycle(cwd=repo)
    lock_path = repo / ".jj/kata.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(KataError) as failure, lifecycle.lock():
            pass

    assert failure.value.code == 75


def test_missing_provision_and_kanban_executables_are_concise(tmp_path: Path) -> None:
    provision = init_repo(tmp_path / "provision")
    (provision / "jjkata.toml").write_text(
        'provision_hook = "scripts/does-not-exist"\n'
    )
    created = workflow(provision, "start", "kept", check=False)
    assert created.returncode == 2
    assert "provision hook does not exist" in created.stderr
    assert "Traceback" not in created.stderr
    assert not (provision / ".workspaces/kept").exists()

    inspection = tmp_path / "inspection"
    inspection.mkdir()
    (inspection / "jjkata.toml").write_text(
        '[kanban]\ncommand = "scripts/does-not-exist"\n'
    )
    result = workflow(inspection, "kanban", "board", check=False)
    assert result.returncode == 2
    assert "could not run Kanban command" in result.stderr
    assert "Traceback" not in result.stderr


def test_provisioning_only_runs_when_a_hook_is_configured(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    scripts = repo / "scripts"
    scripts.mkdir()
    marker = repo / "provisioned.txt"
    hook = scripts / "provision-workspace"
    hook.write_text(f'#!/bin/sh\necho "$1" > {marker}\n')
    hook.chmod(0o755)

    workflow(repo, "start", "unprovisioned")
    assert not marker.exists()

    (repo / "kata.toml").write_text('provision_hook = "scripts/provision-workspace"\n')
    workflow(repo, "start", "provisioned")
    assert marker.read_text().strip() == str(repo / ".workspaces/provisioned")


def test_boundary_check_rejects_semantic_lookalikes(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    jj(
        repo,
        "config",
        "set",
        "--repo",
        'revset-aliases."immutable_heads()"',
        "builtin_immutable_heads() | (working_copies() & default@ & none())",
    )

    result = workflow(repo, "start", "unsafe", check=False)

    assert result.returncode == 2
    assert "needs its teacher" in result.stderr


def test_lifecycle_rejects_older_jj_before_mutation(tmp_path: Path) -> None:
    class OldJj:
        def text(self, *args: str, cwd: Path) -> str:
            if args[0] == "workspace":
                return str(tmp_path)
            if args == ("--version",):
                return "jj 0.42.0"
            raise AssertionError(args)

    with pytest.raises(KataError, match="requires jj 0.43.0 or newer") as failure:
        Lifecycle(cwd=tmp_path, jj=OldJj())  # type: ignore[arg-type]

    assert failure.value.code == 2
