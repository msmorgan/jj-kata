---
name: kata
description: "Use in a Kata-configured Jujutsu repository before beginning feature, fix, documentation, or other deliverable work; when starting, claiming, refreshing, integrating, archiving, returning, or retiring a named feature workspace; or when configuring Kata or implementing or debugging an item driver. Kata applies only when kata.toml or jjkata.toml exists in the default workspace; extra jj workspaces, a .workspaces directory, or a branch-per-feature layout do not make a repository Kata's."
---

# jj-kata

Kata governs a repository only when `kata.toml` or `jjkata.toml` sits in its
`default` workspace. It owns the named-workspace lifecycle
`start` -> `refresh` -> `integrate` -> `drop`; `claim` starts or extends work
through a configured item driver. Use jj-sensei for all general jj operations,
workspace boundaries, history shaping outside this lifecycle, and conflict or
stale-workspace repair.

Kata requires jj-sensei's workspace-aware `immutable_heads()` guard. If Kata
reports that the guard is missing, use jj-sensei's boundaries skill to install
or audit it, then retry with the guard active.

## Invariants

**`default` is for coordination only.** Before changing repository content for
any deliverable from `default`, start or claim a named workspace and continue
from the path Kata returns. This applies when only one agent is active too: the
feature workspace is the unit of coordination and recovery.

Inside a feature workspace, change only that feature and keep its ancestry on
the default line rather than another live feature. Bring deliberately closed
work back through Kata's refresh and integration lifecycle.

**Treat WIP tickets owned by another workspace as read-only.** Ownership covers
notes, dependencies, renames, deletions, and status moves. A bare `start` does
not acquire inherited WIP tickets. Record follow-up work in an owned ticket or
ask the coordinator to arrange a handoff.

The bundled Kanban driver checks every unintegrated change before refresh or
integration. If it reports an unowned WIP edit, remove that edit from the
offending change in your feature workspace; a later revert does not repair the
earlier change. Leave the owning workspace and claim untouched.

## Launcher

Resolve the plugin-root launcher from this loaded `SKILL.md`. For
`/PLUGIN/skills/kata/SKILL.md`, every invocation below means
`/PLUGIN/scripts/kata`; run it from the workspace it should act on. Never
substitute a repository script or a `kata` found on `PATH`.

Preserve the command's exit status and output without piping it. Exit 0 is the
completion criterion. For any other exit, stop and read
[lifecycle recovery and exceptional operations](references/lifecycle-details.md)
before proceeding.

## Lifecycle

### 1. Start or claim from `default`

Choose `start` for ad-hoc work or when no `[items].driver` is configured. Choose
`claim` for repository-defined work:

```bash
/PLUGIN/scripts/kata start NAME
/PLUGIN/scripts/kata claim ITEM
/PLUGIN/scripts/kata claim ITEM... --name NAME
/PLUGIN/scripts/kata claim HOST_NAME --or-start
```

On success, a newly created workspace path is printed to stdout. Use that exact
path as the working directory for every subsequent tool call. This step is
complete only when commands are running from the named feature workspace, not
from `default`.

To attach more items to an existing workspace, run one of these and remain in
the owning feature workspace afterward:

```bash
# From default
/PLUGIN/scripts/kata claim ITEM... --into NAME

# From the owning feature workspace
/PLUGIN/scripts/kata claim ITEM...
```

Item IDs are opaque. A single `claim ITEM` uses the item ID as the workspace
name; use `--name NAME` when it is not a legal or useful name, or when several
items start together.

### 2. Work and close the feature

Make and verify the requested change inside the feature workspace. Before
integration, close the work with `jj --no-pager commit -m "..."`. The feature
is closed only when its working-copy `@` is empty and undescribed.

### 3. Refresh before review or integration

Run refresh unconditionally immediately before final review or integration; an
already-current no-op is successful and removes the need to infer whether
`default` moved:

```bash
# From the feature workspace
/PLUGIN/scripts/kata refresh

# Or from default
/PLUGIN/scripts/kata refresh NAME
```

After a changed refresh, preserve prior results for behavior untouched by the
changes incorporated from `default`. Rerun only the checks whose behavior those
changes could affect under the repository's verification policy. This step is
complete when refresh exits 0 without conflicts.

### 4. Integrate the closed feature

```bash
# From the feature workspace
/PLUGIN/scripts/kata integrate

# Or from default
/PLUGIN/scripts/kata integrate NAME
```

Integration folds the deliberately closed feature changes into the default
line and parks the feature workspace on the integrated tip. This step is
complete when integration exits 0.

### 5. Retire the integrated workspace from `default`

Return subsequent tool calls to the default workspace, then run:

```bash
/PLUGIN/scripts/kata drop NAME
```

The lifecycle is complete when drop exits 0 and reports that the named
workspace was retired.

## Conditional reference

- For bulk refresh, `archive`, forced or item-returning drop, concurrency
  recovery, conflicts, and nonzero exits, read
  [lifecycle recovery and exceptional operations](references/lifecycle-details.md).
- When configuring Kata, visibility, provisioning, or host hooks, read
  [configuration](references/configuration.md).
- When implementing or debugging a repository item driver, read
  [the item-driver protocol](references/item-driver.md).
