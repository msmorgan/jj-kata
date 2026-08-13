# jj-workflow

`jj-workflow` is the workflow-specific layer that jj-sensei deliberately does
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
`jj-workflow` console entry point are also provided.

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

## Feature lifecycle

Load the `jj-workflow` skill and invoke its bundled command by absolute path. If
the installed skill is `/PLUGIN/skills/jj-workflow/SKILL.md`:

```bash
/PLUGIN/skills/jj-workflow/scripts/workflow claim ticket-slug
cd .workspaces/ticket-slug
# work, then close the change with jj commit -m ...
/PLUGIN/skills/jj-workflow/scripts/workflow refresh
/PLUGIN/skills/jj-workflow/scripts/workflow integrate
cd ../..
/PLUGIN/skills/jj-workflow/scripts/workflow drop ticket-slug
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
/PLUGIN/skills/kanban/scripts/kanban board
/PLUGIN/skills/kanban/scripts/kanban ready
/PLUGIN/skills/kanban/scripts/kanban blocked
/PLUGIN/skills/kanban/scripts/kanban graph CARD
/PLUGIN/skills/kanban/scripts/kanban check
```

The inspector searches upward for `docs/tickets`. `--root PATH` selects a board
explicitly. `KANBAN_COLUMNS`, `KANBAN_WIP_COLUMN`, and `KANBAN_DONE_COLUMN`
customize both inspection and lifecycle column names.

