from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import load_config, section
from .errors import KataError
from .items import ItemDriver, Transition, load_driver
from .jj import Jj

EXPECTED_STOP = 69
LOCK_TIMEOUT = 75
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def note(message: str) -> None:
    print(f"jj-kata: {message}", file=sys.stderr)


class Lifecycle:
    def __init__(self, cwd: Path | None = None, jj: Jj | None = None) -> None:
        self.jj = jj or Jj()
        self.invocation_cwd = (cwd or Path.cwd()).resolve()
        self.current_root = Path(
            self.jj.text("workspace", "root", cwd=self.invocation_cwd)
        ).resolve()
        self.default_root = Path(
            self.jj.text(
                "workspace", "root", "--name", "default", cwd=self.current_root
            )
        ).resolve()
        self._require_workspace_boundaries()
        self.config: dict[str, Any] = load_config(self.default_root)
        lifecycle = section(self.config, "lifecycle")
        self.visibility = str(
            lifecycle.get("visibility", self.config.get("visibility", "feature"))
        )
        if self.visibility not in {"feature", "shared"}:
            raise KataError("visibility must be 'feature' or 'shared'", 2)
        self.item_driver: ItemDriver | None = load_driver(
            self.config, self.default_root
        )
        self.unbankable: set[str] = set()

    def _require_workspace_boundaries(self) -> None:
        configured = self.jj.run(
            "config",
            "list",
            "--repo",
            cwd=self.default_root,
            check=False,
        ).stdout
        definition = next(
            (
                line
                for line in configured.splitlines()
                if line.startswith('revset-aliases."immutable_heads()"')
            ),
            "",
        )
        protects_workspaces = (
            "working_copies()" in definition or "other_workspaces()" in definition
        )
        distinguishes_default = (
            "default@" in definition or "not_default()" in definition
        )
        if not (protects_workspaces and distinguishes_default):
            raise KataError(
                "jj-kata needs its teacher: install jj-sensei from "
                "msmorgan/marketplace, then use its boundaries skill to configure "
                "this repository",
                2,
            )

    @contextmanager
    def lock(self) -> Iterator[None]:
        lock_path = self.default_root / ".jj" / "kata.lock"
        timeout = float(
            os.environ.get(
                "JJ_KATA_LOCK_TIMEOUT",
                os.environ.get("JJ_WORKFLOW_LOCK_TIMEOUT", "600"),
            )
        )
        deadline = time.monotonic() + timeout
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock_file:
            while True:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise KataError(
                            f"timed out waiting for {lock_path}", LOCK_TIMEOUT
                        ) from None
                    time.sleep(0.1)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    @property
    def on_default(self) -> bool:
        return self.current_root == self.default_root

    def validate_name(self, name: str) -> None:
        if name == "default" or not NAME_RE.fullmatch(name):
            raise KataError(
                "workspace names use letters, digits, '.', '_', and '-' and may not "
                f"be 'default' (got {name!r})",
                2,
            )

    def bookmark_revset(self, name: str) -> str:
        self.validate_name(name)
        return f'bookmarks(exact:"{name}")'

    def workspace_names(self) -> list[str]:
        return self.jj.lines(
            "workspace",
            "list",
            "-T",
            'name ++ "\\n"',
            "--ignore-working-copy",
            cwd=self.default_root,
        )

    def workspace_root(self, name: str) -> Path:
        if name != "default":
            self.validate_name(name)
        result = self.jj.run(
            "workspace",
            "root",
            "--name",
            name,
            cwd=self.default_root,
            check=False,
        )
        if result.returncode:
            raise KataError(f"no live workspace named {name!r}", 2)
        return Path(result.stdout.strip()).resolve()

    def current_workspace_name(self) -> str:
        for name in self.workspace_names():
            if self.workspace_root(name) == self.current_root:
                return name
        raise KataError("could not identify the current workspace")

    def bookmark_exists(self, name: str) -> bool:
        return bool(
            self.jj.run(
                "log",
                "--no-graph",
                "-r",
                self.bookmark_revset(name),
                "-T",
                "change_id",
                "--ignore-working-copy",
                cwd=self.default_root,
                check=False,
            ).stdout.strip()
        )

    def _change_id(self, revset: str, cwd: Path | None = None) -> str:
        return self.jj.text(
            "log",
            "--no-graph",
            "-r",
            revset,
            "-T",
            "change_id",
            "--ignore-working-copy",
            cwd=cwd or self.default_root,
        )

    def _changes(self, revset: str, cwd: Path | None = None) -> list[str]:
        return self.jj.lines(
            "log",
            "--no-graph",
            "-r",
            revset,
            "-T",
            'change_id ++ "\\n"',
            "--ignore-working-copy",
            cwd=cwd or self.default_root,
        )

    def _is_empty(self, revset: str, cwd: Path | None = None) -> bool:
        return (
            self.jj.text(
                "log",
                "--no-graph",
                "-r",
                revset,
                "-T",
                "empty",
                "--ignore-working-copy",
                cwd=cwd or self.default_root,
            )
            == "true"
        )

    def _live(self, revset: str) -> bool:
        return bool(
            self.jj.run(
                "log",
                "--no-graph",
                "-r",
                revset,
                "-T",
                "change_id",
                "--ignore-working-copy",
                cwd=self.default_root,
                check=False,
            ).stdout.strip()
        )

    def require_default(self, command: str) -> None:
        if not self.on_default:
            raise KataError(f"{command!r} runs from the default workspace", 2)

    def require_self_or_default(self, name: str) -> None:
        if not self.on_default and self.current_workspace_name() != name:
            raise KataError(f"cannot act on {name!r} from another feature workspace", 2)

    def require_linear_default(self) -> None:
        anchor = self.jj.run(
            "log",
            "--no-graph",
            "-r",
            "default@- & fork_point(default@-)",
            "-T",
            "change_id",
            "--ignore-working-copy",
            cwd=self.default_root,
            check=False,
        ).stdout.strip()
        if not anchor:
            raise KataError(
                "default@ is a merge; the coordinator line must be linear", 2
            )

    def workspace_base(self) -> Path:
        configured = str(self.config.get("workspace_dir", ".workspaces"))
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = self.default_root / path
        return path.resolve()

    def bank_workspaces(self) -> None:
        self.unbankable.clear()
        for name in self.workspace_names():
            try:
                root = self.workspace_root(name)
                snapshot = self.jj.run("util", "snapshot", cwd=root, check=False)
            except KataError:
                self.unbankable.add(name)
                continue
            if snapshot.returncode:
                self.unbankable.add(name)
        if self.unbankable:
            note(
                "leaving stale workspace(s) untouched: "
                + ", ".join(sorted(self.unbankable))
            )

    def unstale_workspaces(self) -> None:
        for name in self.workspace_names():
            if name in self.unbankable:
                continue
            try:
                root = self.workspace_root(name)
            except KataError:
                continue
            self.jj.run("workspace", "update-stale", cwd=root, check=False)

    def snapshot_one(self, root: Path) -> None:
        self.jj.run("workspace", "update-stale", cwd=root, check=False)
        self.jj.run("st", cwd=root)

    def _ignore_workspace_base(self, base: Path) -> None:
        try:
            base.relative_to(self.default_root)
        except ValueError:
            return
        ignore = base / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")

    def _cleanup_created(self, name: str, anchor_id: str, ws_dir: Path) -> None:
        if name in self.workspace_names():
            self.jj.run("workspace", "forget", name, cwd=self.default_root, check=False)
        if self.bookmark_exists(name):
            self.jj.run("bookmark", "forget", name, cwd=self.default_root, check=False)
        if anchor_id and self._live(anchor_id):
            self.jj.run("abandon", anchor_id, cwd=self.default_root, check=False)
        if ws_dir.exists():
            shutil.rmtree(ws_dir)

    def _provision(self, ws_dir: Path) -> None:
        provision = Path(
            str(self.config.get("provision_hook", "scripts/provision-workspace"))
        )
        if not provision.is_absolute():
            provision = self.default_root / provision
        if provision.is_file() and os.access(provision, os.X_OK):
            result = subprocess.run([str(provision), str(ws_dir)], check=False)
            if result.returncode:
                raise KataError(f"provision hook failed; workspace remains at {ws_dir}")

    def start(self, name: str) -> Path:
        self.require_default("start")
        self.validate_name(name)
        self.require_linear_default()
        ws_dir = self.workspace_base() / name
        if ws_dir.exists():
            raise KataError(f"workspace directory already exists: {ws_dir}", 2)
        if name in self.workspace_names() or self.bookmark_exists(name):
            raise KataError(f"workspace or bookmark {name!r} already exists", 2)

        ws_dir.parent.mkdir(parents=True, exist_ok=True)
        self._ignore_workspace_base(self.workspace_base())
        anchor_id = ""
        try:
            if self.visibility == "shared":
                self.jj.run(
                    "new",
                    "--no-edit",
                    "-A",
                    "default@- & fork_point(default@-)",
                    "-B",
                    "default@",
                    "-m",
                    f"kata: start {name}",
                    cwd=self.default_root,
                )
                anchor_id = self._change_id("default@-")
                self.jj.run(
                    "bookmark", "create", name, "-r", anchor_id, cwd=self.default_root
                )
                revision = self.bookmark_revset(name)
            else:
                revision = "default@-"
            self.jj.run(
                "workspace", "add", str(ws_dir), "-r", revision, cwd=self.default_root
            )
        except KataError:
            self._cleanup_created(name, anchor_id, ws_dir)
            raise
        self._provision(ws_dir)
        return ws_dir

    def _driver(self) -> ItemDriver:
        if self.item_driver is None:
            raise KataError(
                "claim needs an item driver; configure [items].driver "
                '(for example, driver = "kanban")',
                2,
            )
        return self.item_driver

    @staticmethod
    def _filesets(paths: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(f"root-file:{json.dumps(path)}" for path in paths)

    def _feature_base(self, name: str) -> str:
        return f"fork_point(default@ | {name}@)"

    def _item_context(self, name: str) -> tuple[str, str]:
        if self.visibility == "shared" and self.bookmark_exists(name):
            revision = self.bookmark_revset(name)
            return f"({revision})-", revision
        return self._feature_base(name), f"{name}@"

    def _transition(
        self,
        action: str,
        name: str,
        *,
        root: Path,
        requested: tuple[str, ...] = (),
    ) -> Transition:
        base, revision = self._item_context(name)
        return self._driver().transition(
            action,
            root=root,
            workspace=name,
            requested=requested,
            base_revision=base,
            revision=revision,
            visibility=self.visibility,
        )

    def ownership(self, name: str, ws_dir: Path | None = None) -> Transition:
        return self._transition("owned", name, root=ws_dir or self.workspace_root(name))

    def owned_items(self, name: str, ws_dir: Path | None = None) -> tuple[str, ...]:
        return self.ownership(name, ws_dir).items

    def _claim_change(self, name: str, ws_dir: Path) -> str | None:
        changes = self._changes(
            f'default@..{name}@ & description(glob:"kata: claim *")', cwd=ws_dir
        )
        return changes[0] if len(changes) == 1 else None

    def adopt(self, into: str, items: list[str]) -> None:
        if not items:
            raise KataError("claim needs at least one item", 2)
        self.validate_name(into)
        ws_dir = self.workspace_root(into)
        if len(set(items)) != len(items):
            raise KataError("an item may only be named once", 2)
        requested = tuple(items)

        if self.visibility == "shared":
            if not self.bookmark_exists(into):
                raise KataError(f"no shared claim anchor named {into!r}", 2)
            self.bank_workspaces()
            transition = self._transition(
                "claim", into, root=self.default_root, requested=requested
            )
            try:
                self.jj.run(
                    "squash",
                    "--from",
                    "@",
                    "--into",
                    self.bookmark_revset(into),
                    "-m",
                    f"kata: claim {', '.join(sorted(set(self.owned_items(into) + requested)))}",
                    "--",
                    *self._filesets(transition.paths),
                    cwd=self.default_root,
                )
            except KataError:
                self.jj.run(
                    "restore",
                    "--",
                    *self._filesets(transition.paths),
                    cwd=self.default_root,
                    check=False,
                )
                raise
            finally:
                self.unstale_workspaces()
            return

        existing = self.owned_items(into, ws_dir)
        claim_change = self._claim_change(into, ws_dir)
        transition = self._transition("claim", into, root=ws_dir, requested=requested)
        try:
            claimed = tuple(sorted(set(existing + requested)))
            if claim_change:
                self.jj.run(
                    "squash",
                    "--from",
                    "@",
                    "--into",
                    claim_change,
                    "-m",
                    f"kata: claim {', '.join(claimed)}",
                    "--",
                    *self._filesets(transition.paths),
                    cwd=ws_dir,
                )
            else:
                self.jj.run(
                    "commit",
                    "-m",
                    f"kata: claim {', '.join(claimed)}",
                    "--",
                    *self._filesets(transition.paths),
                    cwd=ws_dir,
                )
        except KataError:
            self.jj.run(
                "restore",
                "--",
                *self._filesets(transition.paths),
                cwd=ws_dir,
                check=False,
            )
            raise

    def claim(
        self,
        items: list[str],
        *,
        into: str | None = None,
        or_start: bool = False,
        workspace_name: str | None = None,
    ) -> Path | None:
        if into:
            if or_start or workspace_name:
                raise KataError("--into does not combine with --or-start or --name", 2)
            self.require_default("claim --into")
            self.adopt(into, items)
            note(f"claimed {', '.join(items)} into {into}")
            return None

        if not self.on_default:
            if or_start:
                raise KataError("--or-start only runs from default", 2)
            name = self.current_workspace_name()
            self.adopt(name, items)
            note(f"claimed {', '.join(items)} into {name}")
            return None

        if workspace_name is None and len(items) != 1:
            raise KataError(
                "claim needs --name when starting a workspace for multiple items", 2
            )
        name = workspace_name or items[0]
        if or_start:
            if self.item_driver is None:
                return self.start(name)
            probe = self.item_driver.transition(
                "probe",
                root=self.default_root,
                workspace=name,
                requested=tuple(items),
                visibility=self.visibility,
            )
            if probe.items != tuple(items):
                return self.start(name)

        ws_dir = self.start(name)
        anchor_id = (
            self._change_id(self.bookmark_revset(name))
            if self.bookmark_exists(name)
            else ""
        )
        try:
            self.adopt(name, items)
        except KataError:
            self._cleanup_created(name, anchor_id, ws_dir)
            raise
        return ws_dir

    def _conflicts(self, revset: str, cwd: Path) -> bool:
        return bool(
            self.jj.run(
                "log",
                "--no-graph",
                "-r",
                f"({revset}) & conflicts()",
                "-T",
                "change_id",
                "--ignore-working-copy",
                cwd=cwd,
                check=False,
            ).stdout.strip()
        )

    def _conflict_stop(self, what: str, ws_dir: Path) -> None:
        raise KataError(
            f"{what}; resolve it in {ws_dir} with jj-sensei's harmony skill, then retry",
            EXPECTED_STOP,
        )

    def _refresh_detach(self, name: str) -> None:
        self.require_linear_default()
        ws_dir = self.workspace_root(name)
        revset = f"default@..{name}@"
        if not self._changes(revset, cwd=ws_dir):
            self.jj.run("workspace", "update-stale", cwd=ws_dir, check=False)
            return
        self.jj.run("rebase", "-r", revset, "-d", "default@-", cwd=ws_dir)
        conflicted = self._conflicts(revset, ws_dir)
        self.jj.run("workspace", "update-stale", cwd=ws_dir, check=False)
        if conflicted:
            self._conflict_stop(f"{name} now conflicts with the default tip", ws_dir)

    def _refresh_reorder(self, name: str) -> None:
        self.require_linear_default()
        ws_dir = self.workspace_root(name)
        if not self.bookmark_exists(name):
            raise KataError(f"{name!r} has no shared claim anchor", 2)
        roots = self._changes(f"roots(default@..{name}@)")
        if len(roots) != 1:
            raise KataError(
                f"{name}'s stack has {len(roots)} roots; it cannot be reordered", 2
            )
        root = roots[0]
        self.jj.run(
            "rebase",
            "-r",
            self.bookmark_revset(name),
            "-B",
            "default@",
            cwd=self.default_root,
        )
        stack = f"{root}:: & ::{name}@"
        self.jj.run(
            "rebase",
            "-r",
            stack,
            "-d",
            self.bookmark_revset(name),
            cwd=self.default_root,
        )
        self.jj.run("workspace", "update-stale", cwd=ws_dir, check=False)
        if self._conflicts(stack, self.default_root):
            self._conflict_stop(f"{name} now conflicts with default", ws_dir)

    def refresh(self, name: str | None = None, *, all_workspaces: bool = False) -> None:
        if all_workspaces:
            self.require_default("refresh --all")
            if name:
                raise KataError("refresh --all takes no workspace name", 2)
            targets = [item for item in self.workspace_names() if item != "default"]
            self.bank_workspaces()
            targets = [target for target in targets if target not in self.unbankable]
            try:
                for target in targets:
                    if self.visibility == "shared":
                        self._refresh_reorder(target)
                    else:
                        self._refresh_detach(target)
            finally:
                self.unstale_workspaces()
            note(f"refreshed {len(targets)} workspace(s)")
            return

        if self.on_default:
            if not name:
                raise KataError(
                    "refresh needs a workspace name on default, or --all", 2
                )
            self.bank_workspaces()
            try:
                if name in self.unbankable:
                    raise KataError(
                        f"{name!r} could not be snapshotted and was left untouched", 2
                    )
                if self.visibility == "shared":
                    self._refresh_reorder(name)
                else:
                    self._refresh_detach(name)
            finally:
                self.unstale_workspaces()
            return

        current = self.current_workspace_name()
        if name and name != current:
            raise KataError("a feature workspace may only refresh itself", 2)
        self._refresh_detach(current)

    def _require_closed(self, name: str, ws_dir: Path) -> None:
        self.snapshot_one(ws_dir)
        if not self._is_empty(f"{name}@", cwd=ws_dir):
            raise KataError(
                f"{name}@ still holds work; commit it and leave an empty change",
                EXPECTED_STOP,
            )
        description = self.jj.text(
            "log",
            "--no-graph",
            "-r",
            f"{name}@",
            "-T",
            "description",
            "--ignore-working-copy",
            cwd=ws_dir,
        )
        if description:
            raise KataError(
                f"{name}@ is described but empty; finish or clear it before integrate",
                EXPECTED_STOP,
            )

    def _complete_feature_items(
        self, target: str, ws_dir: Path, items: tuple[str, ...]
    ) -> None:
        if not items:
            return
        transition = self._transition("complete", target, root=ws_dir, requested=items)
        self.jj.run(
            "commit",
            "-m",
            f"kata: complete {', '.join(items)}",
            "--",
            *self._filesets(transition.paths),
            cwd=ws_dir,
        )

    def _place_feature(self, target: str, ws_dir: Path) -> None:
        wc_id = self._change_id(f"{target}@", cwd=ws_dir)
        selection = f"default@..{target}@-"
        if self._changes(selection):
            self.jj.run(
                "rebase",
                "-r",
                selection,
                "-A",
                "default@- & fork_point(default@-)",
                "-B",
                "default@",
                cwd=self.default_root,
            )
            if self._conflicts("default@", self.default_root):
                self._conflict_stop(
                    f"folding {target} into default conflicts with the default line",
                    self.default_root,
                )
        if self._live(wc_id):
            self.jj.run("rebase", "-r", wc_id, "-d", "@-", cwd=self.default_root)

    def _place_shared(self, target: str, ws_dir: Path) -> tuple[str, bool, str]:
        claim_id = self._change_id(self.bookmark_revset(target))
        claim_empty = self._is_empty(self.bookmark_revset(target))
        wc_id = self._change_id(f"{target}@", cwd=ws_dir)
        self._refresh_detach(target)
        fork_parent = self.jj.run(
            "log",
            "--no-graph",
            "-r",
            f"fork_point(default@..{target}@)-",
            "-T",
            "change_id",
            "--ignore-working-copy",
            cwd=self.default_root,
            check=False,
        ).stdout.strip()
        if fork_parent and fork_parent != claim_id:
            self.jj.run(
                "rebase",
                "-r",
                self.bookmark_revset(target),
                "-A",
                f"fork_point(default@..{target}@)-",
                cwd=self.default_root,
            )
            self.jj.run("workspace", "update-stale", cwd=ws_dir, check=False)
            if self._conflicts(f"{self.bookmark_revset(target)}::", self.default_root):
                self._conflict_stop(
                    f"re-joining {target}'s claim conflicts with default", ws_dir
                )
        selection = f"{self.bookmark_revset(target)} | default@..{target}@-"
        self.jj.run(
            "rebase",
            "-r",
            selection,
            "-A",
            "default@- & fork_point(default@-)",
            "-B",
            "default@",
            cwd=self.default_root,
        )
        if self._conflicts("default@", self.default_root):
            self._conflict_stop(
                f"folding {target} into default conflicts", self.default_root
            )
        return claim_id, claim_empty, wc_id

    def integrate(self, name: str | None = None) -> None:
        target = name or self.current_workspace_name()
        self.validate_name(target)
        self.require_self_or_default(target)
        if self.visibility == "shared" and not self.bookmark_exists(target):
            raise KataError(f"{target!r} has no shared claim anchor", 2)
        ws_dir = self.workspace_root(target)
        self.require_linear_default()
        self._require_closed(target, ws_dir)
        behind = self._changes(f"{target}@-..default@- & ~empty()")
        if behind:
            raise KataError(
                f"{target} is behind default; run jj-kata refresh inside it first", 2
            )
        items = self.owned_items(target, ws_dir) if self.item_driver else ()

        if self.visibility == "feature":
            self._complete_feature_items(target, ws_dir, items)
            self.bank_workspaces()
            self._refresh_detach(target)
            self._place_feature(target, ws_dir)
        else:
            self.bank_workspaces()
            claim_id, claim_empty, wc_id = self._place_shared(target, ws_dir)
            if items:
                transition = self._transition(
                    "complete", target, root=self.default_root, requested=items
                )
                self.jj.run(
                    "commit",
                    "-m",
                    f"kata: complete {', '.join(items)}",
                    "--",
                    *self._filesets(transition.paths),
                    cwd=self.default_root,
                )
            self.jj.run("bookmark", "forget", target, cwd=self.default_root)
            if claim_empty and self._live(claim_id):
                self.jj.run("abandon", claim_id, cwd=self.default_root)
            if self._live(wc_id):
                self.jj.run("rebase", "-r", wc_id, "-d", "@-", cwd=self.default_root)
        self.unstale_workspaces()
        note(f"integrated {target}; retire it with jj-kata drop {target}")

    def _unintegrated_changes(self, name: str) -> list[str]:
        return self._changes(f"(default@..{name}@) ~ empty()")

    def _unintegrated_paths(self, name: str) -> set[str]:
        paths: set[str] = set()
        for change in self._unintegrated_changes(name):
            paths.update(
                self.jj.lines(
                    "diff",
                    "-r",
                    change,
                    "--name-only",
                    "--ignore-working-copy",
                    cwd=self.default_root,
                )
            )
        return paths

    def _drop_one(self, name: str, ws_dir: Path) -> None:
        self.bank_workspaces()
        claim_id = (
            self._change_id(self.bookmark_revset(name))
            if self.bookmark_exists(name)
            else ""
        )
        stack = self._changes(f"default@..{name}@")
        self.jj.run("workspace", "forget", name, cwd=self.default_root)
        if claim_id:
            self.jj.run("bookmark", "forget", name, cwd=self.default_root)
        live = [
            change for change in [claim_id, *stack] if change and self._live(change)
        ]
        if live:
            self.jj.run("abandon", *dict.fromkeys(live), cwd=self.default_root)
        if ws_dir.exists():
            shutil.rmtree(ws_dir)
        self.unstale_workspaces()

    @staticmethod
    def _capture_paths(root: Path, paths: tuple[str, ...]) -> dict[str, bytes | None]:
        captured: dict[str, bytes | None] = {}
        for relative in paths:
            path = root / relative
            captured[relative] = path.read_bytes() if path.is_file() else None
        return captured

    def _apply_paths(
        self, name: str, items: tuple[str, ...], captured: dict[str, bytes | None]
    ) -> None:
        for relative, content in captured.items():
            path = self.default_root / relative
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        paths = tuple(captured)
        changed = self.jj.lines(
            "diff",
            "--name-only",
            "--",
            *self._filesets(paths),
            cwd=self.default_root,
        )
        if changed:
            self.jj.run(
                "commit",
                "-m",
                f"items: return {', '.join(items)}",
                "--",
                *self._filesets(paths),
                cwd=self.default_root,
            )
            note(f"dropped {name} and returned its item edits")
        else:
            note(f"dropped {name}; its items were unedited")

    def drop(
        self,
        name: str | None,
        *,
        force: bool = False,
        amend_ticket: bool = False,
        integrated: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.require_default("drop")
        if integrated:
            if name or force or amend_ticket:
                raise KataError(
                    "drop --integrated takes no name, --force, or --return-items", 2
                )
            self._drop_integrated(dry_run=dry_run)
            return
        if dry_run:
            raise KataError("--dry-run only applies to drop --integrated", 2)
        if not name:
            raise KataError("drop needs a workspace name", 2)
        self.validate_name(name)
        ws_dir = self.workspace_root(name)
        self.snapshot_one(ws_dir)

        captured: dict[str, bytes | None] | None = None
        returned_items: tuple[str, ...] = ()
        ownership: Transition | None = None
        if amend_ticket:
            if self.item_driver is None:
                raise KataError("this workspace has no configured item driver", 2)
            ownership = self.ownership(name, ws_dir)
            returned_items = ownership.items
            if not returned_items:
                raise KataError(f"{name!r} owns no work items", 2)

        unintegrated = self._unintegrated_changes(name)
        if unintegrated and not force:
            at_risk = not amend_ticket or bool(
                self._unintegrated_paths(name)
                - set(ownership.paths if ownership else ())
            )
            if at_risk:
                raise KataError(
                    f"{name} has un-integrated work; integrate it or use --force", 2
                )

        if amend_ticket:
            transition = self._transition(
                "return", name, root=ws_dir, requested=returned_items
            )
            captured = self._capture_paths(ws_dir, transition.paths)
        self._drop_one(name, ws_dir)
        if captured is not None:
            self._apply_paths(name, returned_items, captured)
        else:
            note(f"dropped {name}")

    def _drop_integrated(self, *, dry_run: bool) -> None:
        candidates: list[str] = []
        kept: list[str] = []
        for name in self.workspace_names():
            if name == "default" or self.bookmark_exists(name):
                continue
            ws_dir = self.workspace_root(name)
            try:
                self.snapshot_one(ws_dir)
            except KataError:
                kept.append(name)
                continue
            if self._unintegrated_changes(name):
                kept.append(name)
                continue
            candidates.append(name)
        if not dry_run:
            for name in candidates:
                self._drop_one(name, self.workspace_root(name))
        verb = "would drop" if dry_run else "dropped"
        note(
            f"{verb} {len(candidates)} integrated workspace(s): {', '.join(candidates)}"
        )
        if kept:
            note(
                f"kept workspace(s) with resumed or unreadable work: {', '.join(kept)}"
            )
