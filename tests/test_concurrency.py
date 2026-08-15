from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KATA = ROOT / "scripts" / "kata"
TEST_CONFIG_HOME = Path(os.environ["XDG_CONFIG_HOME"])


def environment(config_home: Path, **overrides: str) -> dict[str, str]:
    return {
        **os.environ,
        "NO_COLOR": "1",
        "JJ_KATA_LOCK_TIMEOUT": "5",
        "XDG_CONFIG_HOME": str(config_home),
        **overrides,
    }


def run(
    cwd: Path,
    *args: str | Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        [*map(str, args)],
        cwd=cwd,
        text=True,
        capture_output=True,
        env=env or environment(TEST_CONFIG_HOME),
        check=False,
    )
    if check and process.returncode:
        raise AssertionError(
            f"command failed ({process.returncode}): {' '.join(map(str, args))}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return process


def jj(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(cwd, "jj", "--no-pager", *args, check=check)


def kata(
    cwd: Path,
    config_home: Path,
    *args: str,
    check: bool = True,
    **env_overrides: str,
) -> subprocess.CompletedProcess[str]:
    return run(
        cwd,
        KATA,
        *args,
        check=check,
        env=environment(config_home, **env_overrides),
    )


def init_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
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
    (repo / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    jj(repo, "commit", "-m", "base")
    return repo, TEST_CONFIG_HOME


def add_ticket(repo: Path, slug: str) -> None:
    (repo / "kata.toml").write_text('[items]\ndriver = "kanban"\n', encoding="utf-8")
    planned = repo / "docs/tickets/planned"
    planned.mkdir(parents=True)
    (planned / f"{slug}.md").write_text(f"# {slug}\n", encoding="utf-8")
    jj(repo, "commit", "-m", f"tickets: add {slug}")


def start_closed_feature(
    repo: Path, config_home: Path, name: str, content: str
) -> Path:
    kata(repo, config_home, "start", name)
    workspace = repo / ".workspaces" / name
    (workspace / f"{name}.txt").write_text(content, encoding="utf-8")
    jj(workspace, "commit", "-m", f"feat: {name}")
    return workspace


def workspace_names(repo: Path) -> set[str]:
    return set(
        jj(repo, "workspace", "list", "-T", 'name ++ "\\n"').stdout.strip().splitlines()
    )


def bookmarks(repo: Path) -> set[str]:
    return set(
        jj(repo, "bookmark", "list", "--all", "-T", 'name ++ "\\n"')
        .stdout.strip()
        .splitlines()
    )


def assert_no_divergence(repo: Path) -> None:
    divergent = jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        "divergent()",
        "-T",
        'change_id.short() ++ "\\n"',
    ).stdout
    assert not divergent, f"reachable divergent changes:\n{divergent}"


def assert_no_stale_workspaces(repo: Path) -> None:
    for name in workspace_names(repo):
        root = Path(jj(repo, "workspace", "root", "--name", name).stdout.strip())
        status = jj(root, "st", check=False)
        assert status.returncode == 0, f"{name} is stale:\n{status.stderr}"


def parallel_kata(
    repo: Path,
    config_home: Path,
    commands: list[tuple[Path, tuple[str, ...]]],
) -> list[subprocess.CompletedProcess[str]]:
    if os.name != "posix":
        pytest.skip("POSIX lifecycle lock")
    import fcntl

    lock_path = repo / ".jj/kata.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    processes: list[subprocess.Popen[str]] = []
    with lock_path.open("a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for cwd, args in commands:
            processes.append(
                subprocess.Popen(
                    [str(KATA), *args],
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment(config_home),
                )
            )
        assert all(process.poll() is None for process in processes)
        fcntl.flock(held, fcntl.LOCK_UN)

    results: list[subprocess.CompletedProcess[str]] = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            results.append(
                subprocess.CompletedProcess(
                    process.args, process.returncode, stdout, stderr
                )
            )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()
    return results


def test_parallel_claims_have_one_clean_winner(tmp_path: Path) -> None:
    repo, config_home = init_repo(tmp_path)
    add_ticket(repo, "contended")

    results = parallel_kata(
        repo,
        config_home,
        [
            (repo, ("claim", "contended")),
            (repo, ("claim", "contended")),
        ],
    )

    assert sorted(result.returncode for result in results) == [0, 2]
    loser = next(result for result in results if result.returncode == 2)
    assert "workspace directory already exists" in loser.stderr
    assert "Traceback" not in loser.stderr
    assert workspace_names(repo) == {"default", "contended"}
    assert not bookmarks(repo)
    assert (repo / "docs/tickets/planned/contended.md").is_file()
    assert (repo / ".workspaces/contended/docs/tickets/wip/contended.md").is_file()
    assert_no_stale_workspaces(repo)
    assert_no_divergence(repo)


def test_cli_lock_waits_and_timeout_leaves_no_partial_state(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("POSIX lifecycle lock")
    import fcntl

    waiting_repo, waiting_config = init_repo(tmp_path / "waiting")
    waiting_lock = waiting_repo / ".jj/kata.lock"
    waiting_lock.parent.mkdir(parents=True, exist_ok=True)
    with waiting_lock.open("a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        waiter = subprocess.Popen(
            [str(KATA), "start", "waiter"],
            cwd=waiting_repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment(waiting_config, JJ_KATA_LOCK_TIMEOUT="5"),
        )
        with pytest.raises(subprocess.TimeoutExpired):
            waiter.wait(timeout=0.1)
        assert workspace_names(waiting_repo) == {"default"}
        assert not (waiting_repo / ".workspaces/waiter").exists()
        fcntl.flock(held, fcntl.LOCK_UN)
    stdout, stderr = waiter.communicate(timeout=10)
    assert waiter.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"
    assert workspace_names(waiting_repo) == {"default", "waiter"}
    assert_no_stale_workspaces(waiting_repo)
    assert_no_divergence(waiting_repo)

    timeout_repo, timeout_config = init_repo(tmp_path / "timeout")
    timeout_lock = timeout_repo / ".jj/kata.lock"
    timeout_lock.parent.mkdir(parents=True, exist_ok=True)
    with timeout_lock.open("a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        timed_out = kata(
            timeout_repo,
            timeout_config,
            "start",
            "blocked",
            check=False,
            JJ_KATA_LOCK_TIMEOUT="0",
        )

    assert timed_out.returncode == 75
    assert "timed out waiting" in timed_out.stderr
    assert workspace_names(timeout_repo) == {"default"}
    assert not (timeout_repo / ".workspaces/blocked").exists()
    assert not bookmarks(timeout_repo)
    assert_no_stale_workspaces(timeout_repo)
    assert_no_divergence(timeout_repo)


def test_integrate_banks_dirty_siblings_before_rewriting_default(
    tmp_path: Path,
) -> None:
    repo, config_home = init_repo(tmp_path)
    kata(repo, config_home, "start", "sibling")
    sibling = repo / ".workspaces/sibling"
    precious = sibling / "precious.txt"
    precious.write_text("unsnapshotted sibling edit\n", encoding="utf-8")
    target = start_closed_feature(repo, config_home, "target", "target work\n")

    kata(target, config_home, "integrate")

    assert (repo / "target.txt").read_text(encoding="utf-8") == "target work\n"
    assert precious.read_text(encoding="utf-8") == "unsnapshotted sibling edit\n"
    assert_no_stale_workspaces(repo)
    assert_no_divergence(repo)


def test_integrate_skips_a_preexisting_stale_dirty_sibling(
    tmp_path: Path,
) -> None:
    repo, config_home = init_repo(tmp_path)
    kata(repo, config_home, "start", "victim")
    victim = repo / ".workspaces/victim"
    target = start_closed_feature(repo, config_home, "target", "target work\n")
    (repo / "advance.txt").write_text("default advanced\n", encoding="utf-8")
    jj(repo, "commit", "-m", "default: advance")

    jj(repo, "rebase", "-r", "victim@", "-d", "@-")
    stale_before = jj(victim, "st", check=False)
    assert stale_before.returncode != 0
    assert "working copy is stale" in stale_before.stderr
    precious = victim / "precious.txt"
    precious.write_text("stale unsnapshotted edit\n", encoding="utf-8")

    refreshed = kata(target, config_home, "refresh")
    integrated = kata(target, config_home, "integrate")

    assert "leaving stale workspace(s) untouched: victim" in refreshed.stderr
    assert "leaving stale workspace(s) untouched: victim" in integrated.stderr
    assert precious.read_text(encoding="utf-8") == "stale unsnapshotted edit\n"
    stale_after = jj(victim, "st", check=False)
    assert stale_after.returncode != 0
    assert "working copy is stale" in stale_after.stderr
    assert (repo / "target.txt").is_file()
    assert_no_divergence(repo)


def test_parallel_refresh_integrate_and_drop_preserve_a_dirty_sibling(
    tmp_path: Path,
) -> None:
    repo, config_home = init_repo(tmp_path)
    kata(repo, config_home, "start", "dropping")
    kata(repo, config_home, "integrate", "dropping")
    refreshing = start_closed_feature(
        repo, config_home, "refreshing", "refreshing work\n"
    )
    (repo / "advance.txt").write_text("default advanced\n", encoding="utf-8")
    jj(repo, "commit", "-m", "default: advance")
    integrating = start_closed_feature(
        repo, config_home, "integrating", "integrating work\n"
    )
    kata(repo, config_home, "start", "dirty")
    dirty = repo / ".workspaces/dirty"
    precious = dirty / "precious.txt"
    precious.write_text("concurrent unsnapshotted edit\n", encoding="utf-8")

    results = parallel_kata(
        repo,
        config_home,
        [
            (refreshing, ("refresh",)),
            (integrating, ("integrate",)),
            (repo, ("drop", "dropping")),
        ],
    )

    assert [result.returncode for result in results] == [0, 0, 0]
    assert not (repo / ".workspaces/dropping").exists()
    assert "dropping" not in workspace_names(repo)
    assert (repo / "integrating.txt").is_file()
    assert not (repo / "refreshing.txt").exists()
    assert precious.read_text(encoding="utf-8") == "concurrent unsnapshotted edit\n"
    assert_no_stale_workspaces(repo)
    assert_no_divergence(repo)

    # Integration may have advanced default after the concurrent refresh. A final
    # refresh must still make the remaining feature immediately integrable.
    kata(refreshing, config_home, "refresh")
    kata(refreshing, config_home, "integrate")
    assert (repo / "refreshing.txt").is_file()
    assert precious.read_text(encoding="utf-8") == "concurrent unsnapshotted edit\n"
    assert_no_stale_workspaces(repo)
    assert_no_divergence(repo)
