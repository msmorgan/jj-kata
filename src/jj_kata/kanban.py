from __future__ import annotations

import argparse
import heapq
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .config import find_config, section
from .errors import KataError
from .items import external_command, resolve_command
from .jj import Jj

NEEDS_RE = re.compile(r"^needs:\s*\[(.*)]\s*$")


@dataclass(frozen=True)
class Card:
    slug: str
    column: str
    path: Path
    needs: tuple[str, ...]


@dataclass(frozen=True)
class BoardSettings:
    root: str = "docs/tickets"
    wip: str = "wip"
    done: str = "done"
    patterns: tuple[str, ...] = ("*.md",)
    columns: tuple[str, ...] = ()
    needs_command: tuple[str, ...] | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> BoardSettings:
        value = section(config, "kanban")
        root = value.get("root", "docs/tickets")
        wip = value.get("wip", "wip")
        done = value.get("done", "done")
        patterns_value = value.get("patterns", ["*.md"])
        columns_value = value.get("columns", [])
        needs_value = value.get("needs_command")
        if not isinstance(root, str) or not root:
            raise KataError("kanban.root must be a non-empty string", 2)
        for setting, column in (("wip", wip), ("done", done)):
            if (
                not isinstance(column, str)
                or not column
                or len(PurePosixPath(column).parts) != 1
                or column in {".", ".."}
            ):
                raise KataError(
                    f"kanban.{setting} must be one non-empty folder name", 2
                )
        if wip == done:
            raise KataError("kanban.wip and kanban.done must be different", 2)
        if (
            not isinstance(patterns_value, list)
            or not patterns_value
            or not all(isinstance(item, str) and item for item in patterns_value)
        ):
            raise KataError("kanban.patterns must be a non-empty string array", 2)
        if not isinstance(columns_value, list) or not all(
            isinstance(item, str) and item for item in columns_value
        ):
            raise KataError("kanban.columns must be a string array", 2)
        if len(set(columns_value)) != len(columns_value):
            raise KataError("kanban.columns may not contain duplicates", 2)
        return cls(
            root=root,
            wip=wip,
            done=done,
            patterns=tuple(patterns_value),
            columns=tuple(columns_value),
            needs_command=(
                external_command(needs_value, setting="kanban.needs_command")
                if needs_value is not None
                else None
            ),
        )


class FolderKanbanDriver:
    def __init__(self, settings: BoardSettings, default_root: Path) -> None:
        self.settings = settings
        board = Path(settings.root).expanduser()
        self.board = (board if board.is_absolute() else default_root / board).resolve()
        try:
            self.board_prefix = self.board.relative_to(
                default_root.resolve()
            ).as_posix()
        except ValueError as error:
            raise KataError("kanban.root must be inside the repository", 2) from error
        self.jj = Jj()

    @classmethod
    def from_config(
        cls, config: dict[str, Any], default_root: Path
    ) -> FolderKanbanDriver:
        return cls(BoardSettings.from_config(config), default_root)

    def board_exists(self, root: Path) -> bool:
        return (root / self.board_prefix).is_dir()

    def _matches(self, path: PurePosixPath) -> bool:
        return any(path.match(pattern) for pattern in self.settings.patterns)

    def _parts(self, path: str) -> tuple[str, PurePosixPath] | None:
        pure = PurePosixPath(path)
        prefix = PurePosixPath(self.board_prefix)
        try:
            relative = pure.relative_to(prefix)
        except ValueError:
            return None
        if len(relative.parts) < 2:
            return None
        card_path = PurePosixPath(*relative.parts[1:])
        if not self._matches(card_path):
            return None
        return relative.parts[0], card_path

    @staticmethod
    def _identifier(card_path: PurePosixPath) -> str:
        return card_path.stem

    def _revision_cards(self, root: Path, revision: str) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = defaultdict(dict)
        paths = self.jj.lines(
            "file", "list", "-r", revision, "--ignore-working-copy", cwd=root
        )
        for path in paths:
            parsed = self._parts(path)
            if parsed is None:
                continue
            column, card_path = parsed
            identifier = self._identifier(card_path)
            if identifier in result[column]:
                raise KataError(
                    f"duplicate Kanban item {identifier!r} in {column!r}", 2
                )
            result[column][identifier] = path
        return result

    def _working_cards(self, root: Path) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = defaultdict(dict)
        board = root / self.board_prefix
        if not board.is_dir():
            raise KataError(f"Kanban root is not a directory: {board}", 2)
        for path in sorted(item for item in board.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            parsed = self._parts(relative)
            if parsed is None:
                continue
            column, card_path = parsed
            identifier = self._identifier(card_path)
            if identifier in result[column]:
                raise KataError(
                    f"duplicate Kanban item {identifier!r} in {column!r}", 2
                )
            result[column][identifier] = relative
        return result

    def _claimable_columns(self, cards: dict[str, dict[str, str]]) -> tuple[str, ...]:
        return tuple(
            column
            for column in cards
            if column not in {self.settings.wip, self.settings.done}
        )

    def transition(
        self,
        action: str,
        *,
        root: Path,
        workspace: str,
        requested: tuple[str, ...] = (),
        base_revision: str | None = None,
        revision: str | None = None,
        visibility: str = "feature",
    ) -> Any:
        del workspace, visibility
        from .items import Transition

        if action == "owned":
            if not base_revision or not revision:
                raise KataError("owned requires base and revision context", 2)
            before = self._revision_cards(root, base_revision)
            after = self._revision_cards(root, revision)
            before_wip = set(before.get(self.settings.wip, {}))
            after_wip = set(after.get(self.settings.wip, {}))
            after_paths = {
                path for column in after.values() for path in column.values()
            }
            moved_from_claimable = {
                identifier
                for column in self._claimable_columns(before)
                for identifier, path in before[column].items()
                if path not in after_paths
            }
            owned = moved_from_claimable | (after_wip - before_wip)
            owned_paths = {
                path
                for cards in (*before.values(), *after.values())
                for identifier, path in cards.items()
                if identifier in owned
            }
            return Transition(tuple(sorted(owned)), tuple(sorted(owned_paths)))

        if action == "probe":
            board = root / self.board_prefix
            if not board.exists():
                return Transition((), ())
            if not board.is_dir():
                raise KataError(f"Kanban root is not a directory: {board}", 2)
            cards = self._working_cards(root)
            claimable = self._claimable_columns(cards)
            found: list[str] = []
            for identifier in requested:
                count = sum(identifier in cards[column] for column in claimable)
                if count > 1:
                    raise KataError(f"Kanban item {identifier!r} is ambiguous", 2)
                if count == 1:
                    found.append(identifier)
            return Transition(tuple(found), ())

        cards = self._working_cards(root)
        if len(set(requested)) != len(requested):
            raise KataError("an item may only be named once", 2)
        moves: list[tuple[Path, Path]] = []
        if action == "claim":
            for identifier in requested:
                matches = [
                    cards[column][identifier]
                    for column in self._claimable_columns(cards)
                    if identifier in cards[column]
                ]
                if len(matches) != 1:
                    detail = "not found" if not matches else "ambiguous"
                    raise KataError(f"Kanban item {identifier!r} is {detail}", 2)
                source = root / matches[0]
                destination = root / self.board_prefix / self.settings.wip / source.name
                moves.append((source, destination))
        elif action == "complete":
            for identifier in requested:
                path = cards.get(self.settings.wip, {}).get(identifier)
                if path is None:
                    raise KataError(f"Kanban item {identifier!r} is not in WIP", 69)
                source = root / path
                destination = (
                    root / self.board_prefix / self.settings.done / source.name
                )
                moves.append((source, destination))
        elif action == "return":
            if not base_revision:
                raise KataError("return requires base revision context", 2)
            before = self._revision_cards(root, base_revision)
            claimable = self._claimable_columns(before)
            for identifier in requested:
                source_path = cards.get(self.settings.wip, {}).get(identifier)
                origins = [
                    before[column][identifier]
                    for column in claimable
                    if identifier in before[column]
                ]
                if source_path is None or len(origins) != 1:
                    raise KataError(
                        f"cannot derive a unique return path for {identifier!r}", 2
                    )
                moves.append((root / source_path, root / origins[0]))
        else:
            raise KataError(f"unsupported item-driver action: {action}", 2)

        for source, destination in moves:
            if destination.exists():
                raise KataError(f"item destination already exists: {destination}", 2)
        paths: list[str] = []
        for source, destination in moves:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, destination)
            paths.extend(
                [
                    source.relative_to(root).as_posix(),
                    destination.relative_to(root).as_posix(),
                ]
            )
        return Transition(requested, tuple(paths))

    def inspect(self, arguments: list[str], *, cwd: Path) -> int:
        return main(arguments, cwd=cwd)


def comma_list(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def find_root(
    explicit: str | None,
    *,
    cwd: Path | None = None,
    config_root: Path | None = None,
    configured: str = "docs/tickets",
) -> Path:
    cwd = (cwd or Path.cwd()).resolve()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        nested = candidate / configured
        if nested.is_dir():
            candidate = nested
        if candidate.is_dir():
            return candidate
        raise ValueError(f"board root is not a directory: {candidate}")

    if config_root is not None:
        candidate = (config_root / configured).resolve()
        if candidate.is_dir():
            return candidate
        raise ValueError(f"configured board root is not a directory: {candidate}")

    for directory in (cwd, *cwd.parents):
        candidate = directory / configured
        if candidate.is_dir():
            return candidate
    raise ValueError(f"no {configured} board found; pass --root PATH")


def parse_frontmatter_needs(path: Path) -> tuple[str, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError(f"{path}: ticket is not UTF-8") from error
    if not lines or lines[0].strip() != "---":
        return ()
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = NEEDS_RE.match(line.strip())
        if match:
            return comma_list(match.group(1))
    return ()


class CommandNeeds:
    def __init__(self, command: tuple[str, ...], command_root: Path) -> None:
        self.command = resolve_command(command, command_root)
        self.command_root = command_root

    def __call__(self, path: Path) -> tuple[str, ...]:
        try:
            process = subprocess.run(
                [*self.command, str(path.resolve())],
                cwd=self.command_root,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as error:
            raise ValueError(f"could not query needs for {path}: {error}") from error
        if process.returncode:
            detail = process.stderr.strip() or process.stdout.strip()
            raise ValueError(
                detail or f"needs command failed for {path}",
            )
        needs = tuple(
            line.strip() for line in process.stdout.splitlines() if line.strip()
        )
        if len(set(needs)) != len(needs):
            raise ValueError(f"needs command returned duplicates for {path}")
        return needs


def load_cards(
    root: Path,
    columns: tuple[str, ...],
    patterns: tuple[str, ...] = ("*.md",),
    needs_for: Callable[[Path], tuple[str, ...]] = parse_frontmatter_needs,
) -> tuple[dict[str, Card], list[str]]:
    cards: dict[str, Card] = {}
    problems: list[str] = []
    for column in columns:
        directory = root / column
        if not directory.is_dir():
            continue
        paths = sorted(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and any(path.relative_to(directory).match(pattern) for pattern in patterns)
        )
        for path in paths:
            slug = path.stem
            card = Card(slug, column, path, needs_for(path))
            if slug in cards:
                problems.append(
                    f"duplicate: {slug} appears in {cards[slug].column} and {column}"
                )
            else:
                cards[slug] = card
    return cards, problems


def claimable_columns(columns: tuple[str, ...], wip: str, done: str) -> set[str]:
    return set(columns) - {wip, done}


def blocked_needs(card: Card, cards: dict[str, Card], done: str) -> tuple[str, ...]:
    return tuple(
        need for need in card.needs if need not in cards or cards[need].column != done
    )


def find_cycles(cards: dict[str, Card]) -> list[str]:
    color: dict[str, int] = {}
    stack: list[str] = []
    cycles: set[tuple[str, ...]] = set()

    def visit(slug: str) -> None:
        color[slug] = 1
        stack.append(slug)
        for need in cards[slug].needs:
            if need not in cards:
                continue
            if color.get(need, 0) == 0:
                visit(need)
            elif color.get(need) == 1:
                start = stack.index(need)
                cycle = tuple(stack[start:] + [need])
                rotations = [
                    cycle[index:-1] + cycle[:index] for index in range(len(cycle) - 1)
                ]
                canonical = min(rotations)
                cycles.add(canonical + (canonical[0],))
        stack.pop()
        color[slug] = 2

    for slug in sorted(cards):
        if color.get(slug, 0) == 0:
            visit(slug)
    return ["cycle: " + " -> ".join(cycle) for cycle in sorted(cycles)]


def topological_order(
    cards: dict[str, Card], columns: tuple[str, ...], done: str
) -> tuple[Card, ...]:
    dangling = sorted(
        (card.slug, need)
        for card in cards.values()
        for need in card.needs
        if need not in cards
    )
    if dangling:
        details = ", ".join(f"{slug} needs unknown {need}" for slug, need in dangling)
        raise ValueError(f"cannot order a graph with dangling needs: {details}")

    cycles = find_cycles(cards)
    if cycles:
        raise ValueError("cannot order a cyclic graph: " + "; ".join(cycles))

    remaining = {slug: card for slug, card in cards.items() if card.column != done}
    dependents: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {}
    for slug, card in remaining.items():
        active_needs = tuple(
            dict.fromkeys(need for need in card.needs if need in remaining)
        )
        indegree[slug] = len(active_needs)
        for need in active_needs:
            dependents[need].append(slug)

    rank = {column: index for index, column in enumerate(columns)}

    def key(slug: str) -> tuple[int, str]:
        return rank[remaining[slug].column], slug

    ready = [key(slug) for slug, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ordered: list[Card] = []
    while ready:
        _, slug = heapq.heappop(ready)
        ordered.append(remaining[slug])
        for dependent in dependents[slug]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, key(dependent))
    return tuple(ordered)


def configure_parser(
    parser: argparse.ArgumentParser, *, command_dest: str = "command"
) -> None:
    parser.add_argument("--root", help="ticket directory or project root")
    parser.add_argument(
        "--slugs-only", action="store_true", help="print only slugs where applicable"
    )
    subparsers = parser.add_subparsers(dest=command_dest, required=True)
    subparsers.add_parser("board", help="list cards grouped by column")
    subparsers.add_parser("ready", help="list unblocked claimable cards")
    subparsers.add_parser("blocked", help="list blocked claimable cards")
    subparsers.add_parser("order", help="topologically order unfinished cards")
    for command in ("graph", "needs"):
        child = subparsers.add_parser(command, help=f"show {command} for one card")
        child.add_argument("slug")
    subparsers.add_parser("check", help="validate the dependency graph")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kata kanban",
        description="Inspect a file-backed folder Kanban board.",
    )
    configure_parser(parser)
    return parser


def run(args: argparse.Namespace, *, cwd: Path | None = None) -> int:
    command = getattr(args, "kanban_command", args.command)
    start = (cwd or Path.cwd()).resolve()
    config_root, config = find_config(start)
    settings = BoardSettings.from_config(config)
    done = settings.done
    wip = settings.wip
    root = find_root(
        args.root,
        cwd=start,
        config_root=config_root,
        configured=settings.root,
    )
    discovered = sorted(path.name for path in root.iterdir() if path.is_dir())
    columns = settings.columns
    if columns:
        unlisted = tuple(
            name
            for name in discovered
            if name not in columns and name not in {wip, done}
        )
        states = tuple(
            name for name in (wip, done) if name in discovered and name not in columns
        )
        columns += unlisted + states
    else:
        columns = tuple(name for name in discovered if name not in {wip, done})
        columns += tuple(name for name in (wip, done) if name in discovered)
    if not columns:
        raise ValueError("the board has no column directories")
    if command == "board":
        needs_for = lambda path: ()
    elif settings.needs_command is not None:
        needs_for = CommandNeeds(settings.needs_command, config_root or start)
    else:
        needs_for = parse_frontmatter_needs
    cards, duplicate_problems = load_cards(root, columns, settings.patterns, needs_for)
    claimable = claimable_columns(columns, wip, done)

    if command == "board":
        by_column: dict[str, list[str]] = defaultdict(list)
        for card in cards.values():
            by_column[card.column].append(card.slug)
        for column in columns:
            print(f"{column}:")
            for slug in sorted(by_column[column]):
                print(slug if args.slugs_only else f"  {slug}")
        return 0

    if command in {"ready", "blocked"}:
        ordered = sorted(
            cards.values(), key=lambda item: (columns.index(item.column), item.slug)
        )
        for card in ordered:
            if card.column not in claimable:
                continue
            unmet = blocked_needs(card, cards, done)
            if (command == "ready") != (not unmet):
                continue
            if args.slugs_only:
                print(card.slug)
            elif unmet:
                print(f"{card.slug} ({card.column}) <- {', '.join(unmet)}")
            else:
                print(f"{card.slug} ({card.column})")
        return 0

    if command == "order":
        if duplicate_problems:
            raise ValueError(
                "cannot order a graph with duplicates: " + "; ".join(duplicate_problems)
            )
        for card in topological_order(cards, columns, done):
            print(card.slug if args.slugs_only else f"{card.slug} ({card.column})")
        return 0

    if command in {"graph", "needs"}:
        if args.slug not in cards:
            print(f"kanban: unknown card: {args.slug}", file=sys.stderr)
            return 2
        if command == "needs":
            print("\n".join(cards[args.slug].needs))
            return 0

        seen: set[str] = set()
        upstream: list[str] = []
        queue = list(cards[args.slug].needs)
        while queue:
            need = queue.pop(0)
            if need in seen:
                continue
            seen.add(need)
            upstream.append(need)
            if need in cards:
                queue.extend(cards[need].needs)
        downstream = sorted(
            card.slug for card in cards.values() if args.slug in card.needs
        )

        def display(slug: str) -> str:
            return f"{slug} [{cards[slug].column if slug in cards else '?'}]"

        print("needs (upstream): " + (", ".join(map(display, upstream)) or "(none)"))
        print(
            "blocks (downstream): " + (", ".join(map(display, downstream)) or "(none)")
        )
        return 0

    problems = duplicate_problems[:]
    for card in sorted(cards.values(), key=lambda item: item.slug):
        for need in card.needs:
            if need not in cards:
                problems.append(f"dangling: {card.slug} needs unknown {need}")
    problems.extend(find_cycles(cards))
    if problems:
        print("FAIL")
        print("\n".join(problems))
        return 1
    print("OK: no duplicates, cycles, or dangling needs")
    return 0


def main(argv: list[str] | None = None, *, cwd: Path | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv), cwd=cwd)
    except (ValueError, KataError) as error:
        print(f"kanban: {error}", file=sys.stderr)
        return 2
