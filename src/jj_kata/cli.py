from __future__ import annotations

import argparse
import sys

from .errors import KataError
from .kanban import configure_parser as configure_kanban_parser
from .kanban import run as run_kanban
from .workflow import Workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jj-kata",
        description="Practice a repeatable Jujutsu feature-workspace lifecycle.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="start an ad-hoc feature workspace")
    start.add_argument("name")

    claim = commands.add_parser("claim", help="claim ticket-backed work")
    claim.add_argument("tickets", nargs="+")
    claim.add_argument("--into", metavar="WORKSPACE")
    claim.add_argument("--or-start", action="store_true")

    refresh = commands.add_parser("refresh", help="bring feature work up to trunk")
    refresh.add_argument("name", nargs="?")
    refresh.add_argument("--all", action="store_true", dest="all_workspaces")

    integrate = commands.add_parser("integrate", help="fold closed feature work")
    integrate.add_argument("name", nargs="?")

    drop = commands.add_parser("drop", help="retire a feature workspace")
    drop.add_argument("name", nargs="?")
    drop.add_argument("--force", action="store_true")
    drop.add_argument("--amend-ticket", action="store_true")
    drop.add_argument("--integrated", action="store_true")
    drop.add_argument("--dry-run", action="store_true")

    kanban = commands.add_parser(
        "kanban", help="inspect the configured folder Kanban integration"
    )
    configure_kanban_parser(kanban, command_dest="kanban_command")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "kanban":
        return run_kanban(args)
    workflow = Workflow()
    with workflow.lock():
        if args.command == "start":
            print(workflow.start(args.name))
        elif args.command == "claim":
            path = workflow.claim(args.tickets, into=args.into, or_start=args.or_start)
            if path:
                print(path)
        elif args.command == "refresh":
            workflow.refresh(args.name, all_workspaces=args.all_workspaces)
        elif args.command == "integrate":
            workflow.integrate(args.name)
        elif args.command == "drop":
            workflow.drop(
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
    except KataError as error:
        print(f"jj-kata: {error}", file=sys.stderr)
        return error.code
    except KeyboardInterrupt:
        print("jj-kata: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
