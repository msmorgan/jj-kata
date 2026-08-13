---
name: kanban
description: Inspect an optional file-backed Kanban board in a jj-kata repository. Use when work is tracked as files in status folders and the user asks to inspect the board, find ready or blocked work, trace dependencies, validate the graph, or configure the bundled folder Kanban integration.
---

# Kanban

Use the grouped `jj-kata kanban` command. Resolve the plugin-root launcher from
this loaded skill; for `/PLUGIN/skills/kanban/SKILL.md`, run
`/PLUGIN/scripts/jj-kata` from inside the target repository.

```bash
/PLUGIN/scripts/jj-kata kanban board
/PLUGIN/scripts/jj-kata kanban ready
/PLUGIN/scripts/jj-kata kanban blocked
/PLUGIN/scripts/jj-kata kanban graph ITEM
/PLUGIN/scripts/jj-kata kanban needs ITEM
/PLUGIN/scripts/jj-kata kanban check
```

Commands are read-only:

- `board` lists items grouped by column.
- `ready` lists claimable items whose dependencies are done.
- `blocked` lists claimable items with missing or unfinished dependencies.
- `graph ITEM` prints recursive upstream needs and direct downstream items.
- `needs ITEM` prints direct dependency IDs.
- `check` reports duplicates, dangling needs, and dependency cycles; it exits 1
  when problems exist.

The bundled defaults are `docs/tickets`, `wip`, `done`, and `*.md`. Only WIP
and done have special roles; every other immediate folder is claimable.
Kanban is shipped but never implicitly enabled. Configure it as the lifecycle's
item driver only when wanted, plus names and file patterns in `jjkata.toml`:

```toml
[items]
driver = "kanban"

[kanban]
root = "tasks"
wip = "doing"
done = "finished"
patterns = ["*.task"]
columns = ["urgent", "backlog", "doing", "finished"] # optional order
```

Configured columns establish display priority; they do not hide additional
column folders discovered in the repository.

The default Markdown dependency reader recognizes optional
`needs: [item, ...]` frontmatter. To derive dependencies from another ticket
representation, set `[kanban] needs_command = "scripts/ticket-needs"`. Kata
passes it one absolute ticket path at a time; it must print direct dependency
IDs one per line. All bundled graph commands use this adapter.

Set `[kanban] command = "scripts/todo"` to delegate the entire inspection layer
instead. That command need not be the dependency adapter or lifecycle item
driver.

Do not move items merely because inspection exposes their state. Use
`jj-kata claim`, `integrate`, or `drop --return-items` for lifecycle moves.
