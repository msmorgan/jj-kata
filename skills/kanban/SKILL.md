---
name: kanban
description: Use when a jj-kata repository tracks work as files in status folders and the user asks to inspect the board, find ready or blocked work, trace dependencies, validate the graph, or configure the bundled folder Kanban integration.
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

The bundled graph feature reads `needs: [item, ...]` from frontmatter. Set
`[kanban] command = "scripts/todo"` to delegate only the inspection commands to
repository logic. That command need not be the lifecycle item driver.

Do not move items merely because inspection exposes their state. Use
`jj-kata claim`, `integrate`, or `drop --return-items` for lifecycle moves.
