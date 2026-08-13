from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

DEFAULT_COLUMNS = ("bugs", "critical", "planned", "maybe", "wip", "done")
NEEDS_RE = re.compile(r"^needs:\s*\[(.*)]\s*$")


@dataclass(frozen=True)
class Card:
    slug: str
    column: str
    path: Path
    needs: tuple[str, ...]


def comma_list(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def find_root(explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if (candidate / "docs" / "tickets").is_dir():
            candidate = candidate / "docs" / "tickets"
        if candidate.is_dir():
            return candidate
        raise ValueError(f"board root is not a directory: {candidate}")

    for directory in (Path.cwd(), *Path.cwd().parents):
        candidate = directory / "docs" / "tickets"
        if candidate.is_dir():
            return candidate
    raise ValueError("no docs/tickets board found; pass --root PATH")


def parse_needs(path: Path) -> tuple[str, ...]:
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


def load_cards(
    root: Path, columns: tuple[str, ...]
) -> tuple[dict[str, Card], list[str]]:
    cards: dict[str, Card] = {}
    problems: list[str] = []
    for column in columns:
        directory = root / column
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            slug = path.stem
            card = Card(slug, column, path, parse_needs(path))
            if slug in cards:
                problems.append(
                    f"duplicate: {slug} appears in {cards[slug].column} and {column}"
                )
            else:
                cards[slug] = card
    return cards, problems


def triage_columns(columns: tuple[str, ...], wip: str, done: str) -> set[str]:
    boundary = min(
        (columns.index(name) for name in (wip, done) if name in columns),
        default=len(columns),
    )
    return set(columns[:boundary])


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


def configure_parser(
    parser: argparse.ArgumentParser, *, command_dest: str = "command"
) -> None:
    parser.add_argument("--root", help="ticket directory or project root")
    parser.add_argument(
        "--slugs-only", action="store_true", help="print only slugs where applicable"
    )
    subparsers = parser.add_subparsers(dest=command_dest, required=True)
    subparsers.add_parser("board", help="list cards grouped by column")
    subparsers.add_parser("ready", help="list unblocked triage cards")
    subparsers.add_parser("blocked", help="list blocked triage cards")
    for command in ("graph", "needs"):
        child = subparsers.add_parser(command, help=f"show {command} for one card")
        child.add_argument("slug")
    subparsers.add_parser("check", help="validate the dependency graph")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jj-kata kanban",
        description="Inspect a Markdown-folder Kanban board.",
    )
    configure_parser(parser)
    return parser


def run(args: argparse.Namespace) -> int:
    command = getattr(args, "kanban_command", args.command)
    columns = comma_list(os.environ.get("KANBAN_COLUMNS", ",".join(DEFAULT_COLUMNS)))
    done = os.environ.get("KANBAN_DONE_COLUMN", "done")
    wip = os.environ.get("KANBAN_WIP_COLUMN", "wip")
    if not columns:
        raise ValueError("KANBAN_COLUMNS must name at least one column")
    root = find_root(args.root)
    cards, duplicate_problems = load_cards(root, columns)
    triage = triage_columns(columns, wip, done)

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
            if card.column not in triage:
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


def main(argv: list[str] | None = None) -> int:
    try:
        return run(build_parser().parse_args(argv))
    except ValueError as error:
        print(f"kanban: {error}", file=sys.stderr)
        return 2
