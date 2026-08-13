---
name: kata
description: "Use when a jj repository follows jj-kata's named feature-workspace lifecycle: start or claim repository-defined work, refresh a feature from the default line, integrate deliberately closed work, return claimed items, or retire a workspace. Signs include a default workspace with named feature workspaces, .workspaces/, jjkata.toml, or jjworkflow.toml."
---

# jj-kata

Use Kata for the repository's `start`/`claim` → `refresh` → `integrate` →
`drop` practice. Use jj-sensei for general jj knowledge, boundary setup,
history shaping outside this lifecycle, and stale/divergent/conflicted workspace
repair.

Kata refuses lifecycle commands when the repository lacks a workspace-aware
`immutable_heads()` definition. Use jj-sensei's boundaries skill to install or
audit it; never bypass the refusal.

## Command

Resolve the plugin-root `scripts/jj-kata` from this loaded `SKILL.md`, never
from the target repository or `PATH`. For
`/PLUGIN/skills/kata/SKILL.md`, run `/PLUGIN/scripts/jj-kata` from the workspace
it should act on.

Do not pipe a Kata command. Preserve its exit status: 0 is success, 2 is a
refusal before the transition, 69 leaves an expected state to finish or repair,
75 is lock timeout, and 130 is interruption.

Every command and subcommand supports `--help`.

## Lifecycle

From `default`:

```bash
jj-kata start NAME
jj-kata claim ITEM
jj-kata claim ITEM... --name NAME
jj-kata claim ITEM... --into NAME
jj-kata refresh NAME
jj-kata refresh --all
jj-kata integrate NAME
jj-kata drop NAME
```

From a feature workspace, act only on itself:

```bash
jj-kata claim ITEM...
jj-kata refresh
jj-kata integrate
```

Item IDs are opaque. `claim ITEM` uses the ID as the workspace name only as a
convenience; pass `--name NAME` when that is inappropriate or several items
start together.

Refresh before review or integration when `default` has moved. Integration
requires an empty, undescribed feature `@`; close work with `jj commit -m ...`
first. It folds closed feature changes into the default line and parks the
workspace on the integrated tip. Retire it from `default` with `drop NAME`.

Plain drop refuses unintegrated work. `--force` explicitly discards it.
`--return-items` runs the configured return transition, preserves the paths it
reports, and refuses unrelated work unless `--force` is also explicit.

If refresh or integration reports conflicts, use jj-sensei's harmony skill in
the named workspace. Do not retry past a conflict or perform operation-log
surgery.

## Visibility and state

`visibility = "feature"` is the default. Claims live only on their feature
line, with no Kata bookmark, until integration.

`visibility = "shared"` opts into a bookmarked claim anchor linearly inside the
default tree. Later work based on default sees active claim markers.

Kata has no private claim ledger. The item driver derives ownership from the
base/revision context Kata supplies. A reconstructed graph with the same marker
moves must work without any prior Kata invocation.

When implementing or debugging a repository driver, read
[the item-driver protocol](references/item-driver.md).

## Configuration

Read settings from `jjkata.toml` in the default workspace. Legacy
`jjworkflow.toml` remains a migration fallback. Relative paths resolve from the
default root.

```toml
visibility = "feature"
workspace_dir = ".workspaces"
provision_hook = "scripts/provision-workspace"

[items]
driver = "kanban" # or "scripts/items"
```

The provision hook is optional. Kata calls an executable hook with the created
workspace path after creation; a hook failure deliberately leaves that
workspace intact for inspection.
