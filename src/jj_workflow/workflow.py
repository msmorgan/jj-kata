from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .errors import WorkflowError
from .jj import Jj
from .kanban import DEFAULT_COLUMNS, comma_list

EXPECTED_STOP = 69
LOCK_TIMEOUT = 75
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def note(message: str) -> None:
    print(f"workflow: {message}", file=sys.stderr)


class Workflow:
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
        self.config = self._load_config()
        self.unbankable: set[str] = set()

    def _load_config(self) -> dict[str, object]:
        path = self.default_root / "jjworkflow.toml"
        if not path.is_file():
            return {}
        try:
            with path.open("rb") as config_file:
                return tomllib.load(config_file)
        except tomllib.TOMLDecodeError as error:
            raise WorkflowError(f"invalid {path}: {error}", 2) from error

    @contextmanager
    def lock(self) -> Iterator[None]:
        lock_path = self.default_root / ".jj" / "workflow.lock"
        timeout = float(os.environ.get("JJ_WORKFLOW_LOCK_TIMEOUT", "600"))
        deadline = time.monotonic() + timeout
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock_file:
            while True:
                try:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise WorkflowError(
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

    @property
    def columns(self) -> tuple[str, ...]:
        return comma_list(os.environ.get("KANBAN_COLUMNS", ",".join(DEFAULT_COLUMNS)))

    @property
    def wip_column(self) -> str:
        return os.environ.get("KANBAN_WIP_COLUMN", "wip")

    @property
    def done_column(self) -> str:
        return os.environ.get("KANBAN_DONE_COLUMN", "done")

    @property
    def triage_columns(self) -> tuple[str, ...]:
        boundary = min(
            (
                self.columns.index(name)
                for name in (self.wip_column, self.done_column)
                if name in self.columns
            ),
            default=len(self.columns),
        )
        return self.columns[:boundary]

    @property
    def tickets_root(self) -> Path:
        return self.default_root / "docs" / "tickets"

    def validate_name(self, name: str) -> None:
        if name == "default" or not NAME_RE.fullmatch(name):
            raise WorkflowError(
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
            raise WorkflowError(f"no live workspace named {name!r}", 2)
        return Path(result.stdout.strip()).resolve()

    def current_workspace_name(self) -> str:
        for name in self.workspace_names():
            if self.workspace_root(name) == self.current_root:
                return name
        raise WorkflowError("could not identify the current workspace")

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
        return (
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
            ).returncode
            == 0
        )

    def require_default(self, command: str) -> None:
        if not self.on_default:
            raise WorkflowError(f"{command!r} runs from the default workspace", 2)

    def require_self_or_default(self, name: str) -> None:
        if not self.on_default and self.current_workspace_name() != name:
            raise WorkflowError(
                f"cannot act on {name!r} from another feature workspace", 2
            )

    def require_linear_trunk(self) -> None:
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
            raise WorkflowError(
                "default@ is a merge; the coordinator line must be linear", 2
            )

    def workspace_base(self) -> Path:
        configured = str(self.config.get("workspace_dir", ".workspaces"))
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = self.default_root / path
        return path.resolve()

    def ticket_triage_path(self, slug: str, root: Path | None = None) -> Path | None:
        ticket_root = (root or self.default_root) / "docs" / "tickets"
        for column in self.triage_columns:
            candidate = ticket_root / column / f"{slug}.md"
            if candidate.is_file():
                return candidate
        return None

    def ticket_state(self, slug: str) -> str:
        if self.ticket_triage_path(slug):
            return "triage"
        if (self.tickets_root / self.wip_column / f"{slug}.md").is_file():
            return "wip"
        if (self.tickets_root / self.done_column / f"{slug}.md").is_file():
            return "done"
        return "unknown"

    def claim_slugs(self, name: str) -> list[str]:
        if not self.bookmark_exists(name):
            return []
        paths = self.jj.lines(
            "diff",
            "-r",
            self.bookmark_revset(name),
            "--name-only",
            "--ignore-working-copy",
            cwd=self.default_root,
        )
        prefix = f"docs/tickets/{self.wip_column}/"
        return sorted(
            path.removeprefix(prefix).removesuffix(".md")
            for path in paths
            if path.startswith(prefix) and path.endswith(".md")
        )

    def bank_workspaces(self) -> None:
        self.unbankable.clear()
        for name in self.workspace_names():
            try:
                root = self.workspace_root(name)
            except WorkflowError:
                continue
            result = self.jj.run("util", "snapshot", cwd=root, check=False)
            if result.returncode:
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
            except WorkflowError:
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

    def _cleanup_created(self, name: str, claim_id: str, ws_dir: Path) -> None:
        if name in self.workspace_names():
            self.jj.run("workspace", "forget", name, cwd=self.default_root, check=False)
        if self.bookmark_exists(name):
            self.jj.run("bookmark", "forget", name, cwd=self.default_root, check=False)
        if claim_id and self._live(claim_id):
            self.jj.run("abandon", claim_id, cwd=self.default_root, check=False)
        if ws_dir.exists():
            shutil.rmtree(ws_dir)

    def start(self, name: str) -> Path:
        self.require_default("start")
        self.validate_name(name)
        self.require_linear_trunk()
        ws_dir = self.workspace_base() / name
        if ws_dir.exists():
            raise WorkflowError(f"workspace directory already exists: {ws_dir}", 2)
        if name in self.workspace_names() or self.bookmark_exists(name):
            raise WorkflowError(f"workspace or bookmark {name!r} already exists", 2)

        ws_dir.parent.mkdir(parents=True, exist_ok=True)
        self._ignore_workspace_base(self.workspace_base())
        claim_id = ""
        try:
            self.jj.run(
                "new",
                "--no-edit",
                "-A",
                "default@- & fork_point(default@-)",
                "-B",
                "default@",
                "-m",
                f"workflow: start {name}",
                cwd=self.default_root,
            )
            claim_id = self._change_id("default@-")
            self.jj.run(
                "bookmark",
                "create",
                name,
                "-r",
                claim_id,
                cwd=self.default_root,
            )
            self.jj.run(
                "workspace",
                "add",
                str(ws_dir),
                "-r",
                self.bookmark_revset(name),
                cwd=self.default_root,
            )
        except WorkflowError:
            self._cleanup_created(name, claim_id, ws_dir)
            raise

        provision = Path(
            str(self.config.get("provision_hook", "scripts/provision-workspace"))
        )
        if not provision.is_absolute():
            provision = self.default_root / provision
        if provision.is_file() and os.access(provision, os.X_OK):
            result = subprocess.run([str(provision), str(ws_dir)], check=False)
            if result.returncode:
                raise WorkflowError(
                    f"provision hook failed; workspace remains at {ws_dir}"
                )
        return ws_dir

    def adopt(self, into: str, tickets: list[str]) -> None:
        if not tickets:
            raise WorkflowError("claim needs at least one ticket", 2)
        self.validate_name(into)
        self.workspace_root(into)
        if not self.bookmark_exists(into):
            raise WorkflowError(f"no live claim bookmark named {into!r}", 2)
        if len(set(tickets)) != len(tickets):
            raise WorkflowError("a ticket may only be named once", 2)

        moves: list[tuple[Path, Path]] = []
        for ticket in tickets:
            self.validate_name(ticket)
            source = self.ticket_triage_path(ticket)
            if source is None:
                state = self.ticket_state(ticket)
                if state == "wip":
                    raise WorkflowError(f"{ticket!r} is already claimed", 2)
                if state == "done":
                    raise WorkflowError(f"{ticket!r} is already done", 2)
                raise WorkflowError(f"no triage ticket named {ticket!r}", 2)
            destination = self.tickets_root / self.wip_column / source.name
            moves.append((source, destination))

        self.bank_workspaces()
        owned = self.claim_slugs(into)
        paths: list[str] = []
        moved: list[tuple[Path, Path]] = []
        try:
            for source, destination in moves:
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.replace(destination)
                moved.append((source, destination))
                paths.extend(
                    [
                        str(source.relative_to(self.default_root)),
                        str(destination.relative_to(self.default_root)),
                    ]
                )
            slugs = sorted(set(owned + tickets))
            self.jj.run(
                "squash",
                "--from",
                "@",
                "--into",
                self.bookmark_revset(into),
                "-m",
                f"workflow: claim {', '.join(slugs)}",
                "--",
                *paths,
                cwd=self.default_root,
            )
        except WorkflowError:
            for source, destination in reversed(moved):
                if destination.exists() and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    destination.replace(source)
            raise
        finally:
            self.unstale_workspaces()

    def claim(
        self, tickets: list[str], *, into: str | None = None, or_start: bool = False
    ) -> Path | None:
        if into:
            if or_start:
                raise WorkflowError("--into and --or-start do not combine", 2)
            self.require_default("claim --into")
            self.adopt(into, tickets)
            note(f"folded {', '.join(tickets)} into {into}'s claim")
            return None

        if not self.on_default:
            if or_start:
                raise WorkflowError("--or-start only runs from default", 2)
            name = self.current_workspace_name()
            self.adopt(name, tickets)
            note(f"folded {', '.join(tickets)} into {name}'s claim")
            return None

        if len(tickets) != 1:
            raise WorkflowError(
                "claim starts one workspace for one ticket; use --into for extras", 2
            )
        name = tickets[0]
        if or_start and self.ticket_state(name) != "triage":
            ws_dir = self.start(name)
            self.jj.run(
                "describe",
                "-r",
                self.bookmark_revset(name),
                "-m",
                f"workflow: claim {name}",
                cwd=self.default_root,
            )
            self.jj.run("workspace", "update-stale", cwd=ws_dir, check=False)
            return ws_dir

        ws_dir = self.start(name)
        claim_id = self._change_id(self.bookmark_revset(name))
        try:
            self.adopt(name, [name])
        except WorkflowError:
            self._cleanup_created(name, claim_id, ws_dir)
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
        raise WorkflowError(
            f"{what}; resolve it in {ws_dir} with jj-sensei's harmony skill, then retry",
            EXPECTED_STOP,
        )

    def _refresh_detach(self, name: str) -> None:
        self.require_linear_trunk()
        ws_dir = self.workspace_root(name)
        revset = f"default@..{name}@"
        if not self._changes(revset, cwd=ws_dir):
            self.jj.run("workspace", "update-stale", cwd=ws_dir, check=False)
            return
        self.jj.run("rebase", "-r", revset, "-d", "default@-", cwd=ws_dir)
        conflicted = self._conflicts(revset, ws_dir)
        self.jj.run("workspace", "update-stale", cwd=ws_dir, check=False)
        if conflicted:
            self._conflict_stop(f"{name} now conflicts with the trunk tip", ws_dir)

    def _refresh_reorder(self, name: str) -> None:
        self.require_linear_trunk()
        ws_dir = self.workspace_root(name)
        if not self.bookmark_exists(name):
            raise WorkflowError(f"{name!r} has no claim bookmark", 2)
        roots = self._changes(f"roots(default@..{name}@)")
        if len(roots) != 1:
            raise WorkflowError(
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
                raise WorkflowError("refresh --all takes no workspace name", 2)
            targets = [
                item
                for item in self.workspace_names()
                if item != "default" and self.bookmark_exists(item)
            ]
            self.bank_workspaces()
            try:
                for target in targets:
                    self._refresh_reorder(target)
            finally:
                self.unstale_workspaces()
            note(f"refreshed {len(targets)} workspace(s)")
            return

        if self.on_default:
            if not name:
                raise WorkflowError(
                    "refresh needs a workspace name on default, or --all", 2
                )
            self.bank_workspaces()
            try:
                self._refresh_reorder(name)
            finally:
                self.unstale_workspaces()
            return

        current = self.current_workspace_name()
        if name and name != current:
            raise WorkflowError("a feature workspace may only refresh itself", 2)
        self._refresh_detach(current)

    def _require_closed(self, name: str, ws_dir: Path) -> None:
        self.snapshot_one(ws_dir)
        empty = self._is_empty(f"{name}@", cwd=ws_dir)
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
        if not empty:
            raise WorkflowError(
                f"{name}@ still holds work; commit it and leave an empty change",
                EXPECTED_STOP,
            )
        if description:
            raise WorkflowError(
                f"{name}@ is described but empty; finish or clear it before integrate",
                EXPECTED_STOP,
            )

    def _require_wip_tickets(self, name: str, ws_dir: Path, slugs: list[str]) -> None:
        for slug in slugs:
            expected = ws_dir / "docs" / "tickets" / self.wip_column / f"{slug}.md"
            if expected.is_file():
                continue
            landed = next(
                (
                    column
                    for column in self.columns
                    if (ws_dir / "docs" / "tickets" / column / f"{slug}.md").is_file()
                ),
                None,
            )
            location = f"in {landed}/" if landed else "missing"
            raise WorkflowError(
                f"{slug} is no longer in {self.wip_column}/ ({location}); "
                f"restore it there in {name} before integrating, or use "
                "drop --amend-ticket when handing it back",
                EXPECTED_STOP,
            )

    def integrate(self, name: str | None = None) -> None:
        target = name or self.current_workspace_name()
        self.validate_name(target)
        self.require_self_or_default(target)
        if not self.bookmark_exists(target):
            raise WorkflowError(f"{target!r} has no live claim bookmark", 2)
        ws_dir = self.workspace_root(target)
        self.require_linear_trunk()
        self._require_closed(target, ws_dir)
        behind = self._changes(f"{target}@-..default@- & ~empty()")
        if behind:
            raise WorkflowError(
                f"{target} is behind trunk; run workflow refresh inside it first", 2
            )
        slugs = self.claim_slugs(target)
        self._require_wip_tickets(target, ws_dir, slugs)

        self.bank_workspaces()
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
                    f"re-joining {target}'s claim conflicts with trunk", ws_dir
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
                f"folding {target} into default conflicts with trunk", self.default_root
            )

        move_paths: list[str] = []
        for slug in slugs:
            source = self.tickets_root / self.wip_column / f"{slug}.md"
            destination = self.tickets_root / self.done_column / f"{slug}.md"
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
            move_paths.extend(
                [
                    str(source.relative_to(self.default_root)),
                    str(destination.relative_to(self.default_root)),
                ]
            )
        if move_paths:
            self.jj.run(
                "commit",
                "-m",
                f"workflow: complete {' '.join(slugs)}",
                "--",
                *move_paths,
                cwd=self.default_root,
            )

        self.jj.run("bookmark", "forget", target, cwd=self.default_root)
        if claim_empty and self._live(claim_id):
            self.jj.run("abandon", claim_id, cwd=self.default_root)
        if self._live(wc_id):
            self.jj.run("rebase", "-r", wc_id, "-d", "@-", cwd=self.default_root)
        self.unstale_workspaces()
        note(f"integrated {target}; retire it with workflow drop {target}")

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

    def _capture_ticket_text(self, name: str, ws_dir: Path) -> dict[str, bytes]:
        slugs = self.claim_slugs(name)
        if not slugs:
            raise WorkflowError(
                f"{name}'s claim owns no ticket; use plain drop instead", 2
            )
        captured: dict[str, bytes] = {}
        for slug in slugs:
            path = next(
                (
                    ws_dir / "docs" / "tickets" / column / f"{slug}.md"
                    for column in self.columns
                    if (ws_dir / "docs" / "tickets" / column / f"{slug}.md").is_file()
                ),
                None,
            )
            if path is None:
                raise WorkflowError(f"{name} no longer has a ticket file for {slug}", 2)
            captured[slug] = path.read_bytes()
        return captured

    def _apply_ticket_text(self, name: str, captured: dict[str, bytes]) -> None:
        paths: list[str] = []
        for slug, content in captured.items():
            destination = self.ticket_triage_path(slug)
            if destination is None:
                destination = self.tickets_root / self.triage_columns[-1] / f"{slug}.md"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            paths.append(str(destination.relative_to(self.default_root)))
        changed = self.jj.lines(
            "diff", "--name-only", "--", *paths, cwd=self.default_root
        )
        if changed:
            self.jj.run(
                "commit",
                "-m",
                f"tickets: amend {', '.join(captured)}",
                "--",
                *paths,
                cwd=self.default_root,
            )
            note(f"dropped {name} and wrote its ticket edits back to triage")
        else:
            note(f"dropped {name}; its tickets were unedited")

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
                raise WorkflowError(
                    "drop --integrated takes no name, --force, or --amend-ticket", 2
                )
            self._drop_integrated(dry_run=dry_run)
            return
        if dry_run:
            raise WorkflowError("--dry-run only applies to drop --integrated", 2)
        if not name:
            raise WorkflowError("drop needs a workspace name", 2)
        self.validate_name(name)
        ws_dir = self.workspace_root(name)
        self.snapshot_one(ws_dir)
        captured = self._capture_ticket_text(name, ws_dir) if amend_ticket else None
        unintegrated = self._unintegrated_changes(name)
        if unintegrated and not force:
            at_risk = True
            if amend_ticket:
                at_risk = any(
                    not path.startswith("docs/tickets/")
                    for path in self._unintegrated_paths(name)
                )
            if at_risk:
                raise WorkflowError(
                    f"{name} has un-integrated work; integrate it or use --force", 2
                )
        self._drop_one(name, ws_dir)
        if captured is not None:
            self._apply_ticket_text(name, captured)
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
            except WorkflowError:
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
