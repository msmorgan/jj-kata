# jj-kata

Safe Jujutsu workspace coordination for parallel agents, with optional
file-backed Kanban.

`kata` coordinates parallel Jujutsu feature workspaces: create an isolated
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

`default` is a coordinator, not a development workspace. Start or claim a
named workspace before making feature, fix, documentation, or other deliverable
changes, even during single-agent work. Work and close commits inside that
workspace; use `default` for creation, cross-workspace coordination,
integration, and retirement.

There is no cross-host plugin dependency mechanism, so install Kata's teacher
first. For Codex:

```bash
codex plugin marketplace add msmorgan/marketplace
codex plugin add jj-sensei@msmorgan
```

For Claude Code, use `claude plugin marketplace add msmorgan/marketplace` and
`claude plugin install jj-sensei@msmorgan`.

For Antigravity, install `jj-sensei` from `msmorgan/marketplace` through its
plugin UI before adding Kata.

Everything executable in this plugin is Python. The plugin launcher imports the
`src/jj_kata` package directly, while `pyproject.toml` also provides a normal
`kata` console entry point. The former `jj-kata` command remains an equivalent
compatibility alias.

## Lifecycle

Resolve the launcher from the installed plugin rather than from the target
repository or `PATH`:

```bash
/PLUGIN/scripts/kata start feature-name
cd .workspaces/feature-name
# Work, then close the change with jj commit -m ...
/PLUGIN/scripts/kata refresh
/PLUGIN/scripts/kata integrate
cd ../..
/PLUGIN/scripts/kata drop feature-name
```

That core lifecycle has no ticket or Kanban requirement. To start through a
configured item driver instead:

```bash
/PLUGIN/scripts/kata claim ITEM
/PLUGIN/scripts/kata claim ITEM --name feature-name
/PLUGIN/scripts/kata claim HOST_NAME --or-start
/PLUGIN/scripts/kata refresh --all
```

`ITEM` is opaque to Kata. When an item ID is not also a legal jj workspace
name, or several items should start together, pass `--name WORKSPACE`.
Additional items can be folded into a feature with `claim ITEM... --into NAME`
from `default` or `claim ITEM...` from inside the feature.
`--or-start` is the host-hook entry path: it claims a uniquely available item,
but starts an ordinary ad-hoc workspace when the item or optional board is
absent. Ambiguous items and broken drivers still fail loudly.

Integration accepts only an empty, undescribed feature working copy. It folds
the feature's deliberately closed changes immediately before `default@`, then
parks the feature workspace on the integrated tip. `drop` retires it. Plain
drop refuses unintegrated work; `--force` explicitly discards it, and
`--return-items` asks the item driver to return claimed markers while preserving
their edits. Return refuses if `default` changed any governed item path after
the claim, and it keeps the source workspace until the return is committed.
There is deliberately no bulk `drop --integrated`: a fresh empty workspace and
an integrated empty workspace have no unambiguous visible distinction.

## Visibility

The default claim mode is ordinary feature-local work:

```toml
[items]
visibility = "feature"
```

The claim transition lives only on that feature's line. Other workspaces
started later from `default` do not see its WIP marker until integration.
Features have no Kata bookmark.

Repositories that want newly started work to see active claims can opt into:

```toml
[items]
visibility = "shared"
```

Shared visibility preserves the stronger original topology: Kata creates a
bookmarked claim anchor linearly inside the default tree, and folds the claim
transition into it. The bookmark and anchor are publication mechanics, not a
private state database.

A same-named bookmark is not sufficient evidence. Kata recognizes a shared
anchor only when it is the feature/default common fork, the configured driver
derives owned items from that context, and the anchor description matches the
configured claim template. A foreign bookmark is left alone; ambiguous
anchor-shaped state is refused.

Visibility applies only when starting a workspace through `claim`. Bare
`start` always creates an ordinary bookmark-free feature workspace, and the
entire `start` → `refresh` → `integrate` → `drop` lifecycle works without an
`[items]` table or ticket system.

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
folds exactly those paths. An empty path list is a real no-op and never broadens
into unrelated open work. A driver may represent items in an external system,
but ownership must remain derivable from the supplied graph context and that
authoritative system—Kata keeps no private claim ledger. If the visible state
is reconstructed as Kata would have made it, lifecycle commands work without
prior Kata process state.

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
/PLUGIN/scripts/kata kanban board
/PLUGIN/scripts/kata kanban ready
/PLUGIN/scripts/kata kanban blocked
/PLUGIN/scripts/kata kanban order
/PLUGIN/scripts/kata kanban graph ITEM
/PLUGIN/scripts/kata kanban needs ITEM
/PLUGIN/scripts/kata kanban check
```

Dependency extraction is pluggable. By default, the bundled Markdown reader
understands optional `needs: [item, ...]` frontmatter and otherwise ignores the
ticket body. A repository can instead configure
`[kanban] needs_command = "scripts/ticket-needs"`. Kata invokes it once per
ticket with the absolute file path; it prints direct dependency IDs one per
line. The ready, blocked, order, graph, needs, and check commands all consume
that same interface. `order` prints every unfinished item in dependency order,
using column priority and then item ID to break otherwise-equivalent choices;
it validates the entire graph—including done-only subgraphs—before omitting
completed items, and refuses cyclic, dangling, or duplicate graphs.

A repository can replace the entire inspection layer with
`[kanban] command = "scripts/todo"`; this is independent of both the dependency
adapter and lifecycle item driver.

## Configuration and hooks

Copy [`kata.example.toml`](kata.example.toml) to `kata.toml` in a repository's
default workspace. Relative paths resolve from that root. The 0.11.0 filename
`jjkata.toml` remains fully supported for compatibility; do not keep both files
in one repository, because Kata refuses that ambiguity. The clean break still
intentionally refuses a legacy
`jjworkflow.toml`; migrate the wanted settings, then remove the legacy file
before running lifecycle commands.

Kata-authored descriptions are templates with `{workspace}` and `{items}`
fields. Configure any or all of them under `[messages]`:

```toml
[messages]
start = "coordination: open {workspace}"
claim = "coordination: claim {items} for {workspace}"
complete = "coordination: complete {items}"
return = "coordination: return {items}"
```

The Python `hooks/worktree_create.py` and `hooks/worktree_remove.py` bridges are
repository opt-in. The create hook replaces native Git-worktree creation, so
Kata intentionally does not register either bridge in a plugin manifest.

Claude Code supports the required events. Copy
[`hooks/claude-project-hooks.example.json`](hooks/claude-project-hooks.example.json)
to `.claude/settings.json` in the repository, replace
`/ABSOLUTE/PATH/TO/jj-kata` with the installed plugin or checkout root, then
review the project hook in Claude Code. The bridge accepts Claude's
`WorktreeCreate` and `WorktreeRemove` JSON. Generated names must match
`[A-Za-z0-9][A-Za-z0-9._-]*`; names containing `/` are refused. See Claude's
[hook reference](https://docs.anthropic.com/en/docs/claude-code/hooks).

Codex hooks currently have no WorktreeCreate or WorktreeRemove event, so there
is no equivalent safe repository-local registration; use the Kata skill or
commands directly rather than attaching these bridges to another event. See
the [official Codex hooks reference](https://learn.chatgpt.com/docs/hooks.md).
Antigravity likewise has no verified repository-local replacement event in
Kata 0.11; its plugin can use the skills and commands, but not these bridges.

## Requirements and exit contract

The Python package requires Python 3.11 or newer. Lifecycle commands support
POSIX hosts (Linux and macOS), require jj 0.43.0 or newer, and verify a known
jj-sensei boundary configuration before mutation. The read-only bundled Kanban
commands do not import the POSIX lock and remain portable to Windows.

- `0`: completed successfully.
- `2`: configuration/input refusal before Kata mutates lifecycle state.
- `69`: Kata changed or preserved a deliberate recovery state that needs a
  retry, cleanup, or jj-sensei Harmony.
- `75`: timed out waiting for the repository Kata lock.
- `130`: interrupted.

Unexpected jj failures use exit `1`. External item drivers must leave state
unchanged on nonzero exit; Kata reports those failures as `2`. A failed
provision executable runs after workspace creation, returns `69`, and leaves
the workspace for inspection.

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
