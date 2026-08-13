---
name: kanban
description: Use when a repository tracks work as Markdown cards in docs/tickets status folders and the user asks to inspect the board, find ready or blocked work, trace dependencies, or validate the ticket graph.
---

# Kanban

Use the bundled `scripts/kanban` command to inspect a repository's file-backed
ticket board. The directory containing a card is its status column; a card's
filename without `.md` is its slug.

Resolve the command from this loaded `SKILL.md`, never from the project being
inspected. If the loader reports `/PLUGIN/skills/kanban/SKILL.md`, the command
is `/PLUGIN/skills/kanban/scripts/kanban`.

Run it from somewhere inside the target project:

```bash
/PLUGIN/skills/kanban/scripts/kanban board
/PLUGIN/skills/kanban/scripts/kanban ready
/PLUGIN/skills/kanban/scripts/kanban blocked
/PLUGIN/skills/kanban/scripts/kanban graph SLUG
/PLUGIN/skills/kanban/scripts/kanban needs SLUG
/PLUGIN/skills/kanban/scripts/kanban check
```

Commands are read-only:

- `board` lists every card grouped in column order.
- `ready` lists triage cards whose dependencies all exist and are done.
- `blocked` lists triage cards with dangling or unfinished dependencies.
- `graph SLUG` prints all recursive upstream needs and direct downstream cards.
- `needs SLUG` prints the card's direct dependency slugs.
- `check` reports duplicate slugs, dangling needs, and dependency cycles; it
  exits 1 if any are found.

The default board root is the nearest ancestor's `docs/tickets`. Use
`--root PATH` when the board lives elsewhere. By default the recognized columns
are `bugs,critical,planned,maybe,wip,done`, with `done` satisfying dependencies
and all columns before `wip` treated as triage. Repositories may override these
with comma-separated `KANBAN_COLUMNS`, `KANBAN_DONE_COLUMN`, and
`KANBAN_WIP_COLUMN` environment variables.

Do not move cards merely because the board exposes their state. A requested
status change is an ordinary file move and should follow the repository's own
version-control and workflow rules.
