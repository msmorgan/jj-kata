# jj-workflow

> The Jujutsu workflow, workspace-safety, status, and repair features that used
> to live here have moved to [jj-sensei](https://github.com/msmorgan/jj-sensei).

This plugin now contains only a small, file-backed Kanban helper for coding
agents. Cards are Markdown files under `docs/tickets/<column>/`; their directory
is their board column. Optional `needs: [slug, ...]` frontmatter records card
dependencies.

## Install

### Claude Code

```text
/plugin marketplace add msmorgan/jj-workflow
/plugin install jj-workflow@jj-workflow
```

### Codex

```bash
codex plugin marketplace add msmorgan/jj-workflow
codex plugin add jj-workflow@jj-workflow
```

### Antigravity

Install this repository as a custom plugin. `plugin.json` is its native
manifest.

## Board shape

The default columns are:

```text
docs/tickets/
  bugs/
  critical/
  planned/
  maybe/
  wip/
  done/
```

A card may declare dependencies in YAML-style frontmatter:

```markdown
---
needs: [parser-foundation, diagnostics-api]
---
# Preserve source spans
```

Load the `kanban` skill and run its bundled command by absolute path. If the
skill loader reports `/PLUGIN/skills/kanban/SKILL.md`, use:

```bash
/PLUGIN/skills/kanban/scripts/kanban board
/PLUGIN/skills/kanban/scripts/kanban ready
/PLUGIN/skills/kanban/scripts/kanban blocked
/PLUGIN/skills/kanban/scripts/kanban graph CARD
/PLUGIN/skills/kanban/scripts/kanban check
```

The command searches upward from the current directory for `docs/tickets`.
Pass `--root PATH` to select a board explicitly. Override the recognized column
order with `KANBAN_COLUMNS` (a comma-separated list) and the completed column
with `KANBAN_DONE_COLUMN`.

The plugin deliberately ships no jj hooks, workspace lifecycle, setup,
conflict repair, status reporting, or handoff machinery. Install jj-sensei for
those concerns.
