"""What an agent needs to know on arrival in a Kata-governed repository.

Orientation answers three questions before the agent's first turn: is this a Kata
repository at all, which workspace did the agent land in, and can Kata's lifecycle
commands run here. It reads state and never changes it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .boundaries import boundaries_installed
from .config import CONFIG_NAMES, load_config, section
from .errors import KataError
from .jj import Jj

WORKSPACE_TEMPLATE = 'name ++ "\\t" ++ root ++ "\\n"'
SKILL_POINTER = "Load the `kata` skill before any workspace lifecycle action."
COORDINATOR_GUIDANCE = (
    "`default` is the coordinator line. Unless specifically instructed otherwise, "
    "do not do feature work here: run `kata start NAME` or `kata claim ITEM` from "
    "`default`, then make the change inside that named workspace."
)
FEATURE_GUIDANCE = (
    "You are inside the `{workspace}` feature workspace. Work only on "
    "`{workspace}`, and never base work on another live feature's ancestry. Close "
    "the work with `jj commit -m ...`, then bring it back through `kata refresh` "
    "and `kata integrate` rather than editing the coordinator line."
)
BOUNDARIES_WARNING = (
    "⚠ This repository has no jj-sensei workspace boundaries, so Kata refuses "
    "every lifecycle command. Install them with jj-sensei's boundaries skill; "
    "never bypass the refusal."
)
TRACKED_WARNING = (
    "⚠ The workspace directory is not ignored: {paths} {verb} tracked in this "
    "repository and will ride into the coordinator's next commit. Ignore "
    "{directory} globally or in this repository, then remove what has already "
    "been committed."
)
TRACKED_SAMPLE = 3


@dataclass(frozen=True)
class Orientation:
    workspace: str
    on_default: bool
    default_root: Path
    workspaces: tuple[str, ...]
    items: str
    boundaries: bool
    workspace_dir: str
    tracked: tuple[str, ...]


def orient(cwd: Path, jj: Jj | None = None) -> Orientation | None:
    """Describe the Kata repository containing ``cwd``, or return None.

    Returning None is the ordinary outcome: most repositories are not Kata's, and
    a startup probe that guesses is worse than one that stays quiet.
    """
    if _jj_workspace(cwd) is None:
        return None
    jj = jj or Jj()
    try:
        default_root = _root(jj, cwd, "default")
        if default_root is None or not _configured(default_root):
            return None
        current_root = _root(jj, cwd)
        if current_root is None:
            return None
        workspaces = _workspaces(jj, current_root)
        config = _config(default_root)
        relative = _workspace_dir(config, default_root)
        return Orientation(
            workspace=_name(current_root, default_root, workspaces),
            on_default=current_root == default_root,
            default_root=default_root,
            workspaces=_ordered(workspaces),
            items=_items(config),
            boundaries=boundaries_installed(
                jj.run("config", "list", "--repo", cwd=default_root, check=False).stdout
            ),
            workspace_dir=relative or "",
            tracked=_tracked(jj, default_root, relative),
        )
    except (KataError, OSError, ValueError):
        return None


def render(orientation: Orientation) -> str:
    role = "coordinator" if orientation.on_default else "feature workspace"
    state = f"jj-kata: {orientation.workspace} ({role}) | items: {orientation.items}"
    # A lone default workspace is what the coordinator line already says; only
    # siblings the agent could collide with are worth the room.
    if len(orientation.workspaces) > 1:
        state += f" | live: {', '.join(orientation.workspaces)}"
    guidance = (
        COORDINATOR_GUIDANCE
        if orientation.on_default
        else FEATURE_GUIDANCE.format(workspace=orientation.workspace)
    )
    blocks = [state]
    if not orientation.boundaries:
        blocks.append(BOUNDARIES_WARNING)
    if orientation.tracked:
        blocks.append(_tracked_warning(orientation))
    blocks += [guidance, SKILL_POINTER]
    return "\n\n".join(blocks) + "\n"


def _tracked_warning(orientation: Orientation) -> str:
    shown = list(orientation.tracked[:TRACKED_SAMPLE])
    remaining = len(orientation.tracked) - len(shown)
    paths = ", ".join(f"`{path}`" for path in shown)
    if remaining:
        paths += f" and {remaining} more"
    return TRACKED_WARNING.format(
        paths=paths,
        verb="is" if len(orientation.tracked) == 1 else "are",
        directory=f"`{orientation.workspace_dir}/`",
    )


def _jj_workspace(start: Path) -> Path | None:
    """Rule out non-jj directories before spending a subprocess on them.

    A repository holding a kata.toml but no jj workspace is not a Kata repository,
    and most sessions start somewhere jj has never been.
    """
    try:
        resolved = start.resolve()
    except OSError:
        return None
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".jj").exists():
            return candidate
    return None


def _configured(default_root: Path) -> bool:
    return any((default_root / name).is_file() for name in CONFIG_NAMES)


def _root(jj: Jj, cwd: Path, name: str | None = None) -> Path | None:
    arguments = ["workspace", "root", "--ignore-working-copy"]
    if name is not None:
        arguments += ["--name", name]
    result = jj.run(*arguments, cwd=cwd, check=False)
    if result.returncode:
        return None
    location = result.stdout.strip()
    return Path(location).resolve() if location else None


def _workspaces(jj: Jj, cwd: Path) -> dict[str, Path]:
    result = jj.run(
        "workspace",
        "list",
        "-T",
        WORKSPACE_TEMPLATE,
        "--ignore-working-copy",
        cwd=cwd,
        check=False,
    )
    if result.returncode:
        return {}
    entries: dict[str, Path] = {}
    for line in result.stdout.splitlines():
        name, separator, root = line.partition("\t")
        if name and separator:
            entries[name] = Path(root).resolve()
    return entries


def _ordered(workspaces: dict[str, Path]) -> tuple[str, ...]:
    """Name the coordinator first, then the features alphabetically."""
    features = sorted(name for name in workspaces if name != "default")
    return (*(["default"] if "default" in workspaces else []), *features)


def _name(current: Path, default_root: Path, workspaces: dict[str, Path]) -> str:
    for name, root in workspaces.items():
        if root == current:
            return name
    # jj answered the two root queries but not the listing, or listed a template
    # this jj cannot render. The directory Kata created for a workspace carries
    # its name, so fall back to that rather than dropping orientation entirely.
    return "default" if current == default_root else current.name


def _config(default_root: Path) -> dict[str, Any] | None:
    """Return the repository's Kata settings, or None when they cannot be read."""
    try:
        return load_config(default_root)
    except KataError:
        return None


def _workspace_dir(config: dict[str, Any] | None, default_root: Path) -> str | None:
    """Give the workspace base as a repository-relative path, or None if outside it.

    A base outside the repository needs no ignore rule, because nothing under it
    can reach this repository's working copy in the first place.
    """
    configured = str((config or {}).get("workspace_dir", ".workspaces"))
    base = Path(configured).expanduser()
    if not base.is_absolute():
        base = default_root / base
    try:
        relative = base.resolve().relative_to(default_root)
    except (OSError, ValueError):
        return None
    return str(relative) if relative.parts else None


def _tracked(jj: Jj, default_root: Path, relative: str | None) -> tuple[str, ...]:
    """List repository files under the workspace base.

    Kata writes an ignore file when it first creates the base, but it declines to
    overwrite one that already exists, and a repository may drop or weaken it
    later. Rather than reimplement gitignore precedence across global excludes,
    repository rules, and per-directory files, this observes the outcome those
    rules produce: anything jj tracks here is, by definition, not ignored, and is
    already riding along in the coordinator's commits.
    """
    if relative is None:
        return ()
    result = jj.run(
        "file",
        "list",
        "--ignore-working-copy",
        "--",
        f"root:{json.dumps(relative)}",
        cwd=default_root,
        check=False,
    )
    if result.returncode:
        return ()
    return tuple(line for line in result.stdout.splitlines() if line)


def _items(config: dict[str, Any] | None) -> str:
    if config is None:
        return "unreadable"
    items = section(config, "items")
    driver = items.get("driver")
    if driver is None:
        return "none"
    described = " ".join(map(str, driver)) if isinstance(driver, list) else str(driver)
    if items.get("visibility") == "shared":
        described += " (shared claims)"
    return described
