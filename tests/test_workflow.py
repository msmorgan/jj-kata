from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KATA = ROOT / "scripts" / "jj-kata"
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
            "JJ_WORKFLOW_LOCK_TIMEOUT": "5",
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
    repo.mkdir()
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
    (repo / "jjkata.toml").write_text('visibility = "shared"\n')
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
