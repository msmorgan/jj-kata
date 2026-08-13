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


def add_ticket(repo: Path, slug: str, column: str = "planned") -> None:
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


def test_ticket_claim_refresh_and_integrate(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "ticket-a")

    workflow(repo, "claim", "ticket-a")
    workspace = repo / ".workspaces" / "ticket-a"
    assert (workspace / "docs" / "tickets" / "wip" / "ticket-a.md").is_file()

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


def test_drop_amend_ticket_preserves_notes_in_triage(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "blocked-ticket")
    workflow(repo, "claim", "blocked-ticket")
    workspace = repo / ".workspaces" / "blocked-ticket"
    ticket = workspace / "docs" / "tickets" / "wip" / "blocked-ticket.md"
    ticket.write_text("# blocked-ticket\n\nBlocked on an upstream API.\n")

    workflow(repo, "drop", "blocked-ticket", "--amend-ticket")

    restored = repo / "docs" / "tickets" / "planned" / "blocked-ticket.md"
    assert "Blocked on an upstream API" in restored.read_text()
    assert not workspace.exists()
    assert (
        jj(repo, "log", "--no-graph", "-r", "default@-", "-T", "description").stdout
        == "tickets: amend blocked-ticket\n"
    )


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
