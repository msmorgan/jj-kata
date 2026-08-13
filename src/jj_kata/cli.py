from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import find_config, section
from .errors import KataError
from .items import ExternalDriver, external_command
from .kanban import configure_parser as configure_kanban_parser
from .kanban import run as run_kanban
from .lifecycle import Lifecycle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jj-kata",
        description=(
            "Safe Jujutsu workspace coordination for parallel agents, with optional "
            "file-backed Kanban."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="start an ad-hoc feature workspace")
    start.add_argument("name")

    claim = commands.add_parser("claim", help="claim repository-defined work items")
    claim.add_argument("tickets", nargs="+", metavar="ITEM")
    claim.add_argument("--name", metavar="WORKSPACE")
    claim.add_argument("--into", metavar="WORKSPACE")
    claim.add_argument("--or-start", action="store_true")

    refresh = commands.add_parser("refresh", help="bring feature work up to default")
    refresh.add_argument("name", nargs="?")
    refresh.add_argument("--all", action="store_true", dest="all_workspaces")

    integrate = commands.add_parser("integrate", help="fold closed feature work")
    integrate.add_argument("name", nargs="?")

    drop = commands.add_parser("drop", help="retire a feature workspace")
    drop.add_argument("name")
    drop.add_argument("--force", action="store_true")
    drop.add_argument(
        "--return-items",
        action="store_true",
        dest="amend_ticket",
        help="return owned items through the configured driver before dropping",
    )
    drop.add_argument(
        "--amend-ticket",
        action="store_true",
        dest="amend_ticket",
        help=argparse.SUPPRESS,
    )
    drop.add_argument("--integrated", action="store_true")
    drop.add_argument("--dry-run", action="store_true")

    kanban = commands.add_parser(
        "kanban", help="inspect the configured folder Kanban integration"
    )
    configure_kanban_parser(kanban, command_dest="kanban_command")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "kanban":
        config_root, config = find_config(Path.cwd())
        if config_root is not None:
            command = section(config, "kanban").get("command")
            if command is not None:
                driver = ExternalDriver(
                    external_command(command, setting="kanban.command"), config_root
                )
                arguments = [args.kanban_command]
                if hasattr(args, "slug"):
                    arguments.append(args.slug)
                return driver.inspect(arguments, cwd=Path.cwd())
        return run_kanban(args)
    lifecycle = Lifecycle()
    with lifecycle.lock():
        if args.command == "start":
            print(lifecycle.start(args.name))
        elif args.command == "claim":
            path = lifecycle.claim(
                args.tickets,
                into=args.into,
                or_start=args.or_start,
                workspace_name=args.name,
            )
            if path:
                print(path)
        elif args.command == "refresh":
            lifecycle.refresh(args.name, all_workspaces=args.all_workspaces)
        elif args.command == "integrate":
            lifecycle.integrate(args.name)
        elif args.command == "drop":
            lifecycle.drop(
                args.name,
                force=args.force,
                amend_ticket=args.amend_ticket,
                integrated=args.integrated,
                dry_run=args.dry_run,
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return dispatch(build_parser().parse_args(argv))
    except (KataError, ValueError) as error:
        print(f"jj-kata: {error}", file=sys.stderr)
        return error.code if isinstance(error, KataError) else 2
    except KeyboardInterrupt:
        print("jj-kata: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
