# jj-kata

`jj-kata` is the workflow-specific layer that jj-sensei deliberately does
not provide: ticket-backed feature workspaces with a
`start`/`claim` → `refresh` → `integrate` → `drop` lifecycle, plus a standalone
Markdown Kanban inspector.

[jj-sensei](https://github.com/msmorgan/jj-sensei) remains the general Jujutsu
foundation. Use it for installed-version jj knowledge, repository boundaries,
status, history-shaping guidance, and conflict/divergence repair. This plugin
assumes that foundation and owns the opinionated project workflow on top.

All executable functionality in this repository is Python. The plugin launchers
load the `src/jj_workflow` package directly, so a plugin install does not need a
separate package-install step. A conventional `pyproject.toml` and
`jj-kata` console entry point are also provided.

## Install

### Claude Code

```text
/plugin marketplace add msmorgan/jj-kata
/plugin install jj-kata@jj-kata
```

### Codex

```bash
codex plugin marketplace add msmorgan/jj-kata
codex plugin add jj-kata@jj-kata
```

### Antigravity

Install this repository as a custom plugin. `plugin.json` is its native
manifest.

## Feature lifecycle

Load the `kata` skill and invoke its bundled command by absolute path. If the
installed skill is `/PLUGIN/skills/kata/SKILL.md`:

```bash
/PLUGIN/scripts/jj-kata claim ticket-slug
cd .workspaces/ticket-slug
# work, then close the change with jj commit -m ...
/PLUGIN/scripts/jj-kata refresh
/PLUGIN/scripts/jj-kata integrate
cd ../..
/PLUGIN/scripts/jj-kata drop ticket-slug
```

`start NAME` creates ad-hoc work. `claim TICKET` moves the matching card from a
triage column into `wip`; `integrate` moves it to `done`. Extra tickets can be
folded into an existing claim with `claim TICKET... --into NAME` from `default`,
or `claim TICKET...` from inside that feature workspace.

The default coordinator owns `start`, cross-feature `claim`, named/all
`refresh`, named `integrate`, and `drop`. A feature workspace can claim into,
refresh, or integrate only itself. Integration requires an empty, undescribed
working-copy change and keeps the workspace parked on the integrated tip until
`drop` retires it.

All settings are optional in `jjworkflow.toml`; see
`jjworkflow.example.toml`. Feature workspaces default to `.workspaces/`, and an
executable `scripts/provision-workspace` is called after creation when present.

The Python `hooks/worktree_create.py` and `hooks/worktree_remove.py` bridge
hosts with WorktreeCreate/WorktreeRemove events to this lifecycle. Register
them per repository only: a WorktreeCreate hook replaces a host's native Git
worktree creation and must not be enabled globally for unrelated repositories.

## Kanban inspector

Cards are Markdown files under `docs/tickets/<column>/`; their directory is the
board column. Optional `needs: [slug, ...]` frontmatter records dependencies.
The default columns are `bugs, critical, planned, maybe, wip, done`.

Load the `kanban` skill and run:

```bash
/PLUGIN/scripts/jj-kata kanban board
/PLUGIN/scripts/jj-kata kanban ready
/PLUGIN/scripts/jj-kata kanban blocked
/PLUGIN/scripts/jj-kata kanban graph CARD
/PLUGIN/scripts/jj-kata kanban check
```

The inspector searches upward for `docs/tickets`. `--root PATH` selects a board
explicitly. `KANBAN_COLUMNS`, `KANBAN_WIP_COLUMN`, and `KANBAN_DONE_COLUMN`
customize both inspection and lifecycle column names.
