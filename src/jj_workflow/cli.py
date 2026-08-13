from __future__ import annotations

import argparse
import sys

from .errors import WorkflowError
from .workflow import Workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workflow",
        description="Manage jj-workflow feature workspaces and ticket claims.",
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
    return parser


def dispatch(args: argparse.Namespace) -> int:
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
    except WorkflowError as error:
        print(f"workflow: {error}", file=sys.stderr)
        return error.code
    except KeyboardInterrupt:
        print("workflow: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
