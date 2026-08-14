---
name: kata
description: "Coordinate safe parallel-agent work through jj-kata's named feature-workspace lifecycle: start or claim repository-defined work, refresh a feature from the default line, integrate deliberately closed work, return claimed items, or retire a workspace. Applies only when the default workspace of a Jujutsu repository holds kata.toml or jjkata.toml. Additional jj workspaces, a .workspaces/ directory, or any branch-per-feature layout do not make a repository Kata's."
---

# jj-kata

Kata governs a repository only when `kata.toml` or `jjkata.toml` sits in its
`default` workspace; without that file, use ordinary jj through jj-sensei.

Use Kata to coordinate parallel feature workspaces through
`start` → `refresh` → `integrate` → `drop`. `claim` optionally attaches
repository-defined work-item transitions. Use jj-sensei for general jj
knowledge, boundary setup, history shaping outside this lifecycle, and
stale/divergent/conflicted workspace repair.

Kata refuses lifecycle commands when the repository lacks a workspace-aware
`immutable_heads()` definition. Install `jj-sensei` from
`msmorgan/marketplace`, then use its boundaries skill to install or audit the
guard; never bypass the refusal.

## Workspace invariant

**Do not do feature work in `default`.** `default` is the coordinator line:
use it to start or claim named workspaces, target cross-workspace operations,
and retire completed work. Before changing repository content for a feature,
fix, documentation task, or other deliverable, run `kata start NAME` or
`kata claim ...` from `default`, then do the work inside that named workspace.

If already inside a non-default workspace, keep working there and act only on
that workspace; never create feature work on another live feature's ancestry.
Integrate the deliberately closed work through Kata rather than developing
directly on the coordinator line. This rule applies even when only one agent is
currently active—the separate workspace is the unit of coordination and safe
recovery.

## Command

Resolve the plugin-root `scripts/kata` from this loaded `SKILL.md`, never
from the target repository or `PATH`. For
`/PLUGIN/skills/kata/SKILL.md`, run `/PLUGIN/scripts/kata` from the workspace
it should act on.

Do not pipe a Kata command. Preserve its exit status: 0 is success, 2 is a
refusal before the transition, 69 leaves an expected state to finish or repair,
75 is lock timeout, and 130 is interruption.

Every command and subcommand supports `--help`.

## Lifecycle

From `default`:

```bash
kata start NAME
kata claim ITEM
kata claim ITEM... --name NAME
kata claim ITEM... --into NAME
kata claim HOST_NAME --or-start
kata refresh NAME
kata refresh --all
kata integrate NAME
kata drop NAME
```

From a feature workspace, act only on itself:

```bash
kata claim ITEM...
kata refresh
kata integrate
```

Item IDs are opaque. `claim ITEM` uses the ID as the workspace name only as a
convenience; pass `--name NAME` when that is inappropriate or several items
start together. With no `[items].driver`, use `start`; no filesystem layout
implicitly enables claims.

Refresh before review or integration when `default` has moved. Integration
requires an empty, undescribed feature `@`; close work with `jj commit -m ...`
first. It folds closed feature changes into the default line and parks the
workspace on the integrated tip. Retire it from `default` with `drop NAME`.

Plain drop refuses unintegrated work. `--force` explicitly discards it.
`--return-items` runs the configured return transition, preserves the paths it
reports, refuses newer default-side item edits, and preserves the source
workspace until the return commit succeeds. There is no bulk drop command:
fresh and integrated empty workspaces are not visibly distinguishable.

If refresh or integration reports conflicts, use jj-sensei's harmony skill in
the named workspace. Do not retry past a conflict or perform operation-log
surgery.

## Visibility and state

`[items] visibility = "feature"` is the default. Claims live only on their
feature line, with no Kata bookmark, until integration.

`[items] visibility = "shared"` opts new claims into a bookmarked anchor
linearly inside the default tree. Later work based on default sees active claim
markers. Bare `start` never creates an anchor and does not consult item
visibility.

Kata has no private claim ledger. The item driver derives ownership from the
base/revision context Kata supplies. A reconstructed graph with the same marker
moves must work without any prior Kata invocation.

Shared anchors require positive visible evidence: the bookmark is the
feature/default common fork, the driver derives owned items there, and its
description matches the configured claim message. Never treat bookmark
existence alone as Kata ownership.

When implementing or debugging a repository driver, read
[the item-driver protocol](references/item-driver.md).

## Configuration

Read settings from canonical `kata.toml` or compatibility `jjkata.toml` in the
default workspace; refuse when both exist. Relative paths resolve from the
default root. `[messages]` may override Kata's `start`,
`claim`, `complete`, and `return` commit-description templates using
`{workspace}` and `{items}` fields.

```toml
workspace_dir = ".workspaces"
provision_hook = "scripts/provision-workspace" # unset by default

[items]
driver = "kanban" # or "scripts/items"
visibility = "feature" # or "shared"; applies only to new claims
```

The bundled Kanban driver is optional. It is a convenient ticket framework,
not a prerequisite or part of the parallel-workspace topology.

The provision hook is off unless `provision_hook` names it; Kata never
discovers one by convention. When set, Kata calls the executable with the
created workspace path after creation. Claims establish visible item ownership
before the hook runs. A hook failure deliberately leaves that workspace and
its claim intact for inspection and repair; stderr markers bracket the hook's
own output.

Use the plugin-root [example configuration](../../kata.example.toml) as the
complete starting point. A legacy `jjworkflow.toml` is a hard migration refusal.

Lifecycle commands require Python 3.11+, jj 0.43.0+, and a POSIX host. The
read-only Kanban subcommand remains portable.

Every host registers a session-orientation hook that reports the current
workspace and configuration on arrival; it reads state only, so trust the
commands rather than that line. Registration for the opt-in worktree bridges is
documented in the plugin-root README; Codex and Antigravity do not currently
offer the equivalent repository-local worktree replacement event.
