from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KATA = ROOT / "scripts" / "kata"
WORKTREE_CREATE = ROOT / "hooks" / "worktree_create.py"
WORKTREE_REMOVE = ROOT / "hooks" / "worktree_remove.py"
TEST_CONFIG_HOME = Path(os.environ["XDG_CONFIG_HOME"])


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


def kata(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
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


def add_ticket(repo: Path, slug: str) -> None:
    config = repo / "jjkata.toml"
    if not config.exists():
        config.write_text('[items]\ndriver = "kanban"\n')
    planned = repo / "docs/tickets/planned"
    planned.mkdir(parents=True, exist_ok=True)
    (planned / f"{slug}.md").write_text(f"# {slug}\n")
    jj(repo, "commit", "-m", f"tickets: add {slug}")


def change_id(repo: Path, revision: str) -> str:
    return jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        revision,
        "-T",
        "change_id",
    ).stdout.strip()


def assert_no_divergence(repo: Path) -> None:
    assert not jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        "divergent()",
        "-T",
        "change_id",
    ).stdout


def test_refresh_refuses_a_merge_default(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    kata(repo, "start", "guarded")
    workspace = repo / ".workspaces/guarded"

    tip = change_id(repo, "default@-")
    jj(repo, "new", tip, "-m", "side a")
    side_a = change_id(repo, "@")
    jj(repo, "new", tip, "-m", "side b")
    side_b = change_id(repo, "@")
    jj(repo, "new", side_a, side_b, "-m", "merge default")
    assert (
        len(
            jj(
                repo,
                "log",
                "--no-graph",
                "-r",
                "default@-",
                "-T",
                'change_id ++ "\\n"',
            ).stdout.splitlines()
        )
        == 2
    )

    result = kata(workspace, "refresh", check=False)

    assert result.returncode == 2
    assert "default@ is a merge" in result.stderr
    assert workspace.is_dir()


def test_feature_workspace_cannot_target_a_sibling_or_start_another(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    kata(repo, "start", "feature-a")
    kata(repo, "start", "feature-b")
    feature_a = repo / ".workspaces/feature-a"
    feature_b = repo / ".workspaces/feature-b"

    cross = kata(feature_a, "integrate", "feature-b", check=False)
    create = kata(feature_a, "start", "feature-c", check=False)

    assert cross.returncode == 2
    assert "cannot act on 'feature-b' from another feature workspace" in cross.stderr
    assert create.returncode == 2
    assert "runs from the default workspace" in create.stderr
    assert feature_a.is_dir()
    assert feature_b.is_dir()
    assert not (repo / ".workspaces/feature-c").exists()


def test_force_drop_is_bounded_around_a_foreign_descendant(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    kata(repo, "start", "doomed")
    doomed = repo / ".workspaces/doomed"
    (doomed / "doomed.txt").write_text("doomed\n")
    jj(doomed, "commit", "-m", "feat: doomed work")
    doomed_work = change_id(doomed, "@-")

    kata(repo, "start", "survivor")
    survivor = repo / ".workspaces/survivor"
    (survivor / "survivor.txt").write_text("survivor\n")
    jj(survivor, "commit", "-m", "feat: survivor work")
    survivor_work = change_id(survivor, "@-")
    jj(survivor, "rebase", "-s", survivor_work, "-d", doomed_work)

    kata(repo, "drop", "doomed", "--force")

    assert not doomed.exists()
    assert "doomed" not in jj(repo, "workspace", "list").stdout
    assert not jj(
        repo,
        "log",
        "--no-graph",
        "-r",
        f"change_id({doomed_work})",
        "-T",
        "change_id",
        check=False,
    ).stdout
    assert (
        jj(
            survivor,
            "log",
            "--no-graph",
            "-r",
            f"change_id({survivor_work})",
            "-T",
            "change_id",
        ).stdout.strip()
        == survivor_work
    )
    assert (survivor / "survivor.txt").read_text() == "survivor\n"
    assert jj(survivor, "st").returncode == 0
    assert_no_divergence(repo)


def test_integrate_banks_a_dirty_foreign_descendant(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    kata(repo, "start", "landing")
    landing = repo / ".workspaces/landing"
    (landing / "landing.txt").write_text("landing\n")
    jj(landing, "commit", "-m", "feat: landing work")
    landing_work = change_id(landing, "@-")

    kata(repo, "start", "sibling")
    sibling = repo / ".workspaces/sibling"
    (sibling / "sibling.txt").write_text("sibling\n")
    jj(sibling, "commit", "-m", "feat: sibling work")
    sibling_work = change_id(sibling, "@-")
    jj(sibling, "rebase", "-s", sibling_work, "-d", landing_work)
    (sibling / "dirty.txt").write_text("unsnapshotted\n")

    kata(repo, "integrate", "landing")

    assert (repo / "landing.txt").read_text() == "landing\n"
    assert not (repo / "sibling.txt").exists()
    assert (sibling / "sibling.txt").read_text() == "sibling\n"
    assert (sibling / "dirty.txt").read_text() == "unsnapshotted\n"
    assert jj(sibling, "st").returncode == 0
    assert_no_divergence(repo)


def test_feature_side_claim_accretes_and_banks_a_dirty_sibling(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "alpha")
    add_ticket(repo, "beta")
    kata(repo, "claim", "alpha")
    alpha = repo / ".workspaces/alpha"
    kata(repo, "start", "sibling")
    sibling = repo / ".workspaces/sibling"
    (sibling / "dirty.txt").write_text("unsnapshotted\n")

    kata(alpha, "claim", "beta")

    assert (alpha / "docs/tickets/wip/alpha.md").is_file()
    assert (alpha / "docs/tickets/wip/beta.md").is_file()
    descriptions = jj(
        alpha,
        "log",
        "--no-graph",
        "-r",
        '::@ & description(glob:"kata: claim *")',
        "-T",
        'description.first_line() ++ "\\n"',
    ).stdout.splitlines()
    assert descriptions == ["kata: claim alpha, beta"]
    assert (sibling / "dirty.txt").read_text() == "unsnapshotted\n"
    assert jj(sibling, "st").returncode == 0
    assert_no_divergence(repo)


@pytest.mark.parametrize(
    ("config", "relative_base"),
    [
        (None, ".workspaces"),
        ('workspace_dir = ".claude/worktrees"\n', ".claude/worktrees"),
    ],
)
def test_in_repo_workspace_bases_self_ignore_without_hiding_feature_files(
    tmp_path: Path, config: str | None, relative_base: str
) -> None:
    repo = init_repo(tmp_path)
    if config is not None:
        (repo / "kata.toml").write_text(config)
        jj(repo, "commit", "-m", "kata: configure workspace directory")

    result = kata(repo, "start", "placed")
    base = repo / relative_base
    workspace = base / "placed"

    assert Path(result.stdout.strip()) == workspace
    assert (base / ".gitignore").read_text() == "*\n"
    assert relative_base not in jj(repo, "file", "list").stdout
    (workspace / "feature.txt").write_text("tracked here\n")
    assert "feature.txt" in jj(workspace, "st").stdout


def test_workspace_dir_parent_override_stays_outside_the_repository(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    (repo / "kata.toml").write_text('workspace_dir = ".."\n')
    jj(repo, "commit", "-m", "kata: configure sibling workspaces")

    result = kata(repo, "start", "outside")
    workspace = tmp_path / "outside"

    assert Path(result.stdout.strip()) == workspace
    assert workspace.is_dir()
    assert not (tmp_path / ".gitignore").exists()
    assert not (repo / ".workspaces").exists()


def test_worktree_create_claims_from_a_feature_using_legacy_payload_keys(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    add_ticket(repo, "ticketed")
    kata(repo, "start", "host")
    host = repo / ".workspaces/host"
    ticketed = repo / ".workspaces/ticketed"
    payload = json.dumps(
        {
            "cwd": str(host),
            "worktree_name": "ticketed",
            "worktree_path": str(ticketed),
        }
    )

    result = run(host, str(WORKTREE_CREATE), input_text=payload)

    assert Path(result.stdout.strip()) == ticketed
    assert (ticketed / "docs/tickets/wip/ticketed.md").is_file()


def test_worktree_remove_keeps_open_work_and_ignores_an_unregistered_path(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path)
    kata(repo, "start", "open-work")
    workspace = repo / ".workspaces/open-work"
    (workspace / "precious.txt").write_text("keep me\n")

    kept = run(
        repo,
        str(WORKTREE_REMOVE),
        input_text=json.dumps({"cwd": str(repo), "name": "open-work"}),
    )
    unrelated = run(
        repo,
        str(WORKTREE_REMOVE),
        input_text=json.dumps(
            {"cwd": str(repo), "worktree_path": str(repo / ".workspaces/other")}
        ),
    )

    assert kept.returncode == 0
    assert "worktree removal kept open-work" in kept.stderr
    assert workspace.is_dir()
    assert (workspace / "precious.txt").read_text() == "keep me\n"
    assert unrelated.returncode == 0
    assert unrelated.stderr == ""


def test_worktree_create_fails_cleanly_outside_a_jj_repository(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    result = run(
        outside,
        str(WORKTREE_CREATE),
        check=False,
        input_text=json.dumps({"cwd": str(outside), "name": "no-repo"}),
    )

    assert result.returncode != 0
    assert "There is no jj repo" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (outside / ".workspaces/no-repo").exists()
