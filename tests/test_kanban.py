import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KATA = ROOT / "scripts/jj-kata"


def card(board: Path, column: str, slug: str, needs=()) -> None:
    directory = board / column
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{slug}.md").write_text(
        f"---\nneeds: [{', '.join(needs)}]\n---\n# {slug}\n"
    )


def run(board: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(KATA), "kanban", "--root", str(board), *args],
        cwd=board.parent,
        capture_output=True,
        text=True,
        env=os.environ,
        check=False,
    )


def test_ready_and_blocked_include_dangling_dependencies(tmp_path):
    board = tmp_path / "docs" / "tickets"
    card(board, "done", "foundation")
    card(board, "planned", "ready-card", ["foundation"])
    card(board, "planned", "waiting-card", ["later"])
    card(board, "critical", "dangling-card", ["missing"])
    card(board, "wip", "later")

    ready = run(board, "ready")
    blocked = run(board, "blocked")

    assert ready.returncode == 0
    assert ready.stdout.splitlines() == ["ready-card (planned)"]
    assert blocked.stdout.splitlines() == [
        "dangling-card (critical) <- missing",
        "waiting-card (planned) <- later",
    ]


def test_graph_reports_recursive_needs_and_direct_blocks(tmp_path):
    board = tmp_path / "tickets"
    card(board, "done", "base")
    card(board, "done", "middle", ["base"])
    card(board, "planned", "top", ["middle"])
    card(board, "planned", "consumer", ["top"])

    result = run(board, "graph", "top")

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "needs (upstream): middle [done], base [done]",
        "blocks (downstream): consumer [planned]",
    ]


def test_check_reports_cycles_dangling_needs_and_duplicates(tmp_path):
    board = tmp_path / "tickets"
    card(board, "planned", "a", ["b", "missing"])
    card(board, "planned", "b", ["a"])
    card(board, "done", "a")

    result = run(board, "check")

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "FAIL",
        "duplicate: a appears in planned and done",
        "dangling: a needs unknown missing",
        "cycle: a -> b -> a",
    ]


def test_board_root_is_discovered_from_a_descendant(tmp_path):
    board = tmp_path / "docs" / "tickets"
    card(board, "bugs", "bug-one")
    cwd = tmp_path / "src" / "nested"
    cwd.mkdir(parents=True)

    result = subprocess.run(
        [str(KATA), "kanban", "--slugs-only", "board"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines()[:2] == ["bugs:", "bug-one"]


def test_configured_order_does_not_hide_repository_columns(tmp_path):
    board = tmp_path / "tickets"
    card(board, "urgent", "first")
    card(board, "backlog", "discovered")
    card(board, "wip", "active")
    (tmp_path / "jjkata.toml").write_text(
        '[kanban]\nroot = "tickets"\ncolumns = ["urgent"]\n'
    )

    result = subprocess.run(
        [str(KATA), "kanban", "--slugs-only", "board"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "urgent:",
        "first",
        "backlog:",
        "discovered",
        "wip:",
        "active",
    ]


def test_empty_pattern_list_is_rejected(tmp_path):
    board = tmp_path / "tickets"
    board.mkdir()
    (tmp_path / "jjkata.toml").write_text('[kanban]\nroot = "tickets"\npatterns = []\n')

    result = subprocess.run(
        [str(KATA), "kanban", "board"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "kanban.patterns must be a non-empty string array" in result.stderr


def test_repository_command_can_derive_needs_from_opaque_ticket_files(tmp_path):
    board = tmp_path / "tickets"
    card(board, "done", "foundation")
    card(board, "planned", "github-42")
    (board / "planned/github-42.md").write_text("github: msmorgan/project#42\n")
    command = tmp_path / "ticket_needs.py"
    command.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

ticket = pathlib.Path(sys.argv[1])
if ticket.read_text().strip() == "github: msmorgan/project#42":
    print("foundation")
"""
    )
    command.chmod(0o755)
    (tmp_path / "jjkata.toml").write_text(
        '[kanban]\nroot = "tickets"\nneeds_command = "./ticket_needs.py"\n'
    )

    needs = subprocess.run(
        [str(KATA), "kanban", "needs", "github-42"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    ready = subprocess.run(
        [str(KATA), "kanban", "ready"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert needs.returncode == 0
    assert needs.stdout == "foundation\n"
    assert ready.returncode == 0
    assert ready.stdout == "github-42 (planned)\n"


def test_board_does_not_invoke_the_dependency_adapter(tmp_path):
    board = tmp_path / "tickets"
    card(board, "planned", "opaque")
    command = tmp_path / "must_not_run.py"
    command.write_text(
        "#!/usr/bin/env python3\nraise SystemExit('dependency adapter was invoked')\n"
    )
    command.chmod(0o755)
    (tmp_path / "jjkata.toml").write_text(
        '[kanban]\nroot = "tickets"\nneeds_command = "./must_not_run.py"\n'
    )

    result = subprocess.run(
        [str(KATA), "kanban", "--slugs-only", "board"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.splitlines() == ["planned:", "opaque"]


def test_order_topologically_sorts_unfinished_cards_with_stable_ties(tmp_path):
    board = tmp_path / "tickets"
    card(board, "done", "landed")
    card(board, "critical", "independent")
    card(board, "planned", "foundation", ["landed"])
    card(board, "wip", "middle", ["foundation"])
    card(board, "planned", "finish", ["middle", "independent"])

    result = run(board, "order")

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "independent (critical)",
        "foundation (planned)",
        "middle (wip)",
        "finish (planned)",
    ]
    assert "landed" not in result.stdout


def test_order_refuses_dangling_and_cyclic_graphs(tmp_path):
    dangling = tmp_path / "dangling"
    card(dangling, "planned", "broken", ["missing"])
    dangling_result = run(dangling, "order")

    cyclic = tmp_path / "cyclic"
    card(cyclic, "planned", "a", ["b"])
    card(cyclic, "planned", "b", ["a"])
    cyclic_result = run(cyclic, "order")

    assert dangling_result.returncode == 2
    assert "dangling needs" in dangling_result.stderr
    assert cyclic_result.returncode == 2
    assert "cyclic graph" in cyclic_result.stderr


def test_order_validates_done_only_subgraphs_before_omitting_them(tmp_path):
    dangling = tmp_path / "done-dangling"
    card(dangling, "done", "landed", ["missing"])
    dangling_result = run(dangling, "order")

    cyclic = tmp_path / "done-cycle"
    card(cyclic, "done", "a", ["b"])
    card(cyclic, "done", "b", ["a"])
    cyclic_result = run(cyclic, "order")

    assert dangling_result.returncode == 2
    assert "dangling needs" in dangling_result.stderr
    assert cyclic_result.returncode == 2
    assert "cyclic graph" in cyclic_result.stderr


def test_missing_needs_adapter_is_reported_without_traceback(tmp_path):
    board = tmp_path / "tickets"
    card(board, "planned", "opaque")
    (tmp_path / "jjkata.toml").write_text(
        '[kanban]\nroot = "tickets"\nneeds_command = "./missing-needs"\n'
    )

    result = subprocess.run(
        [str(KATA), "kanban", "order"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "could not query needs" in result.stderr
    assert "Traceback" not in result.stderr
