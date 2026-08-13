# jj-kata

Safe Jujutsu workspace coordination for parallel agents, with optional
file-backed Kanban.

`jj-kata` coordinates parallel Jujutsu feature workspaces: create an isolated
workspace, refresh it against the shared `default` line, safely fold deliberately
closed work back into that line, and retire the workspace without endangering
its siblings. Repositories can optionally attach work-item transitions to that
practice through a driver.

[jj-sensei](https://github.com/msmorgan/jj-sensei) is the general Jujutsu
foundation. It teaches installed-version jj semantics and installs the
repository boundaries that keep live workspaces from rewriting one another.
Kata assumes those boundaries and owns only the
`start` → `refresh` → `integrate` → `drop` lifecycle plus the optional `claim`
adapter.
Mutating lifecycle commands refuse repositories that do not have a
workspace-aware repository `immutable_heads()` definition; use jj-sensei's
boundaries skill to install or audit it first.

There is no plugin-manifest dependency mechanism, so install Kata's teacher
first:

```bash
codex plugin marketplace add msmorgan/marketplace
codex plugin add jj-sensei@msmorgan
```

For Claude Code, use `claude plugin marketplace add msmorgan/marketplace` and
`claude plugin install jj-sensei@msmorgan`.

Everything executable in this plugin is Python. The plugin launcher imports the
`src/jj_kata` package directly, while `pyproject.toml` also provides a normal
`jj-kata` console entry point.

## Lifecycle

Resolve the launcher from the installed plugin rather than from the target
repository or `PATH`:

```bash
/PLUGIN/scripts/jj-kata start feature-name
cd .workspaces/feature-name
# Work, then close the change with jj commit -m ...
/PLUGIN/scripts/jj-kata refresh
/PLUGIN/scripts/jj-kata integrate
cd ../..
/PLUGIN/scripts/jj-kata drop feature-name
```

That core lifecycle has no ticket or Kanban requirement. To start through a
configured item driver instead:

```bash
/PLUGIN/scripts/jj-kata claim ITEM
/PLUGIN/scripts/jj-kata claim ITEM --name feature-name
```

`ITEM` is opaque to Kata. When an item ID is not also a legal jj workspace
name, or several items should start together, pass `--name WORKSPACE`.
Additional items can be folded into a feature with `claim ITEM... --into NAME`
from `default` or `claim ITEM...` from inside the feature.

Integration accepts only an empty, undescribed feature working copy. It folds
the feature's deliberately closed changes immediately before `default@`, then
parks the feature workspace on the integrated tip. `drop` retires it. Plain
drop refuses unintegrated work; `--force` explicitly discards it, and
`--return-items` asks the item driver to return claimed markers while preserving
their edits.

## Visibility

The default is ordinary feature-local work:

```toml
visibility = "feature"
```

The claim transition lives only on that feature's line. Other workspaces
started later from `default` do not see its WIP marker until integration.
Features have no Kata bookmark.

Repositories that want newly started work to see active claims can opt into:

```toml
visibility = "shared"
```

Shared visibility preserves the stronger original topology: Kata creates a
bookmarked claim anchor linearly inside the default tree, and folds the claim
transition into it. The bookmark and anchor are publication mechanics, not a
private state database.

## Repository-defined work items

Work items are optional. With no `[items].driver`, a repository uses the core
workspace lifecycle and `claim` is unavailable; even a `docs/tickets` tree does
not implicitly select Kanban.

When configured, Kata does not know whether an item is a file, a GitHub issue
handle, or something stranger. A driver owns five transitions:

- `probe`: determine whether an item can be claimed by a host hook.
- `claim`: move requested markers into the repository's active state.
- `owned`: derive this feature's items from its base and current revisions.
- `complete`: move owned markers into the repository's completed state.
- `return`: return owned markers when dropping unfinished work.

The driver returns the repository-relative paths it changed; Kata commits or
folds exactly those paths. There is no invisible claim state. If a jj tree and
its marker moves are reconstructed as Kata would have made them, lifecycle
commands work from that graph alone.

Use the bundled folder Kanban driver:

```toml
[items]
driver = "kanban"
```

Or prescribe a repository executable:

```toml
[items]
driver = "scripts/items"
```

See [the item-driver protocol](skills/kata/references/item-driver.md) for its
JSON contract.

## Optional bundled Kanban

Kanban ships here as a useful ready-made ticket framework, not as part of the
Kata lifecycle. Opt into its claim transitions with
`[items] driver = "kanban"`; otherwise the lifecycle never imports or inspects
Kanban state.

The bundled framework defaults to `docs/tickets`, `wip`, `done`, and `*.md`,
but only the WIP and done roles are special. Every other immediate folder is an
ordinary claimable column. Names, root, and filename patterns are repository
configuration:

```toml
[kanban]
root = "tasks"
wip = "doing"
done = "finished"
patterns = ["*.task", "*.md"]
columns = ["urgent", "backlog", "doing", "finished"] # optional display order
```

`columns` orders familiar columns but is not an allowlist: newly added folder
columns are still discovered and shown.

Inspection is grouped under one subcommand:

```bash
/PLUGIN/scripts/jj-kata kanban board
/PLUGIN/scripts/jj-kata kanban ready
/PLUGIN/scripts/jj-kata kanban blocked
/PLUGIN/scripts/jj-kata kanban order
/PLUGIN/scripts/jj-kata kanban graph ITEM
/PLUGIN/scripts/jj-kata kanban needs ITEM
/PLUGIN/scripts/jj-kata kanban check
```

Dependency extraction is pluggable. By default, the bundled Markdown reader
understands optional `needs: [item, ...]` frontmatter and otherwise ignores the
ticket body. A repository can instead configure
`[kanban] needs_command = "scripts/ticket-needs"`. Kata invokes it once per
ticket with the absolute file path; it prints direct dependency IDs one per
line. The ready, blocked, order, graph, needs, and check commands all consume
that same interface. `order` prints every unfinished item in dependency order,
using column priority and then item ID to break otherwise-equivalent choices;
it refuses cyclic, dangling, or duplicate graphs.

A repository can replace the entire inspection layer with
`[kanban] command = "scripts/todo"`; this is independent of both the dependency
adapter and lifecycle item driver.

## Configuration and hooks

Copy `jjkata.example.toml` to a repository's default workspace. Relative paths
resolve from that root. `jjworkflow.toml` is still read as a migration aid, but
new repositories should use `jjkata.toml`.

The Python `hooks/worktree_create.py` and `hooks/worktree_remove.py` bridge
hosts with WorktreeCreate/WorktreeRemove events. Register them per repository:
the create hook replaces a host's native Git-worktree creation and must not be
enabled globally for unrelated repositories.

## Install

Claude Code:

```text
/plugin marketplace add msmorgan/marketplace
/plugin install jj-kata@msmorgan
```

Codex:

```bash
codex plugin marketplace add msmorgan/marketplace
codex plugin add jj-kata@msmorgan
```

Antigravity can install this repository as a custom plugin through its native
`plugin.json` manifest.
