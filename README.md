# jj-kata

`jj-kata` supplies one opinionated practice on top of Jujutsu: create a named
feature workspace, optionally claim repository-defined work, refresh it, fold
closed work into `default`, and retire the workspace.

[jj-sensei](https://github.com/msmorgan/jj-sensei) is the general Jujutsu
foundation. It teaches installed-version jj semantics and installs the
repository boundaries that keep live workspaces from rewriting one another.
Kata assumes those boundaries and owns only the
`start`/`claim` → `refresh` → `integrate` → `drop` lifecycle.
Mutating lifecycle commands refuse repositories that do not have a
workspace-aware repository `immutable_heads()` definition; use jj-sensei's
boundaries skill to install or audit it first.

Everything executable in this plugin is Python. The plugin launcher imports the
`src/jj_kata` package directly, while `pyproject.toml` also provides a normal
`jj-kata` console entry point.

## Lifecycle

Resolve the launcher from the installed plugin rather than from the target
repository or `PATH`:

```bash
/PLUGIN/scripts/jj-kata start feature-name
/PLUGIN/scripts/jj-kata claim ITEM
/PLUGIN/scripts/jj-kata claim ITEM --name feature-name
cd .workspaces/feature-name
# Work, then close the change with jj commit -m ...
/PLUGIN/scripts/jj-kata refresh
/PLUGIN/scripts/jj-kata integrate
cd ../..
/PLUGIN/scripts/jj-kata drop feature-name
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

Kata does not know what an item file is, where it lives, which extension it
uses, or how dependencies work. A driver owns five transitions:

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

## Bundled Kanban

The out-of-box integration defaults to `docs/tickets`, `wip`, `done`, and
`*.md`, but only the WIP and done roles are special. Every other immediate
folder is an ordinary claimable column. Names, root, and filename patterns are
repository configuration:

```toml
[kanban]
root = "tasks"
wip = "doing"
done = "finished"
patterns = ["*.task", "*.md"]
columns = ["urgent", "backlog", "doing", "finished"] # optional display order
```

Inspection is grouped under one subcommand:

```bash
/PLUGIN/scripts/jj-kata kanban board
/PLUGIN/scripts/jj-kata kanban ready
/PLUGIN/scripts/jj-kata kanban blocked
/PLUGIN/scripts/jj-kata kanban graph ITEM
/PLUGIN/scripts/jj-kata kanban needs ITEM
/PLUGIN/scripts/jj-kata kanban check
```

The bundled inspector understands the optional `needs: [item, ...]`
frontmatter convention. When `[items].driver` names an external command, these
Kanban subcommands are delegated to that repository command instead, allowing
the repository to own its graph format too.

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
/plugin marketplace add msmorgan/jj-kata
/plugin install jj-kata@jj-kata
```

Codex:

```bash
codex plugin marketplace add msmorgan/jj-kata
codex plugin add jj-kata@jj-kata
```

Antigravity can install this repository as a custom plugin through its native
`plugin.json` manifest.
