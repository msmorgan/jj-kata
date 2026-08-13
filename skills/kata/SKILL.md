---
name: kata
description: "Use when working in a jj repository that follows jj-kata's default-coordinator and feature-workspace lifecycle: start or claim work, refresh a feature from the default line, integrate closed work, or retire a workspace. Signs include a default workspace with named feature workspaces, .workspaces/, or jjkata.toml."
---

# jj-kata

This skill owns the workflow-specific layer on top of Jujutsu:

- `start` and `claim` create named feature workspaces.
- `refresh` brings a feature current with the coordinator line.
- `integrate` folds deliberately closed feature work into `default`.
- `drop` retires the workspace and its bounded feature stack.
- Ticket claims move cards from triage to `wip`, then integration moves them to
  `done`.

Use jj-sensei for general jj guidance, repository boundaries/setup, history
shaping outside this lifecycle, status, conflict repair, and divergent or stale
workspace recovery.

## Command location

Resolve the plugin-root `scripts/jj-kata` from this loaded `SKILL.md`, never
from the target repository and never from `PATH`. If this file is
`/PLUGIN/skills/kata/SKILL.md`, the command is:

```bash
/PLUGIN/scripts/jj-kata
```

Run it from the workspace it should act from. The command finds the repository
and `default` workspace from the current directory.

Do not pipe a workflow command. Its exit status is meaningful: 0 is success, 2
is a refusal before the requested lifecycle transition, 69 leaves an expected
state for the operator to fix, and 75 is lock timeout. Capture or redirect its
output only if the exit status is preserved.

## Two-tier lifecycle

The `default` workspace coordinates creation and cross-feature changes:

```bash
jj-kata start NAME
jj-kata claim ITEM
jj-kata claim ITEM... --into NAME
jj-kata refresh NAME
jj-kata refresh --all
jj-kata integrate NAME
jj-kata drop NAME
```

A feature workspace acts only on itself:

```bash
jj-kata claim ITEM...   # add work items to this feature's claim
jj-kata refresh         # detach this feature onto current default
jj-kata integrate       # integrate this feature
```

`start NAME` is ad hoc. `claim TICKET` creates a workspace with the ticket's
slug and moves `docs/tickets/<triage>/TICKET.md` into `wip/` in the claim
commit. `claim --into` and feature-local `claim` add more tickets to the same
claim. `claim NAME --or-start` is reserved for the worktree bridge: it claims a
matching triage card and otherwise starts ad hoc work.

## Refresh and integrate

Refresh a feature before review or integration whenever trunk has moved. A
feature-local refresh rebases only that feature's stack onto `default@-`.
Coordinator refresh reorders the named claim immediately below `default@` and
carries its feature stack with it.

Integration accepts only an empty, undescribed feature `@`. Close the work with
`jj commit -m ...` or otherwise leave a deliberate empty cap first. It refuses
an open, described-empty, behind-trunk, or ticket-inconsistent feature before
folding it.

The ticket move from `wip/` to `done/` belongs to `integrate`; never move or
delete an owned wip ticket by hand. A successful ticketed integration leaves a
`workflow: claim ...` entry and a real `workflow: complete ...` entry in the
history. Integration keeps the workspace parked on the new trunk tip so it can
be inspected or reused; normally retire it next with `drop NAME` from default.

If refresh or integration reports conflicts, use jj-sensei's harmony skill in
the named workspace. Do not retry integration past a conflict and do not perform
operation-log surgery.

## Drop safely

Plain `drop NAME` refuses unintegrated or resumed work. `drop NAME --force`
explicitly discards that workspace's claim and bounded feature stack.

When a ticketed attempt is blocked or premature, edit the ticket with what was
learned and run:

```bash
jj-kata drop NAME --amend-ticket
```

That retires the claim and writes the edited ticket back to its triage column as
`tickets: amend ...`. Work outside `docs/tickets/` still blocks this form unless
`--force` is also explicit.

Use `drop --integrated` to sweep only parked, integrated, empty workspaces;
`drop --integrated --dry-run` previews the same selection.

## Configuration

All settings are optional in repository-root `jjkata.toml`:

```toml
workspace_dir = ".workspaces"
provision_hook = "scripts/provision-workspace"
```

Relative paths resolve from the default workspace root. The provision hook is
an optional executable called with the newly created workspace path.
