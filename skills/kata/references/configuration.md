# Kata configuration

Read settings from canonical `kata.toml` or compatibility `jjkata.toml` in the
default workspace. Kata refuses when both exist. Relative paths resolve from
the default root, and legacy `jjworkflow.toml` is a migration refusal.

Use the plugin-root [example configuration](../../../kata.example.toml) as the
complete starting point. The settings that select Kata's optional branches are:

```toml
workspace_dir = ".workspaces"
provision_hook = "scripts/provision-workspace" # unset by default

[items]
driver = "kanban" # or "scripts/items"
visibility = "feature" # or "shared"; applies only to new claims
```

`[messages]` may override Kata's `start`, `claim`, `complete`, and `return`
commit-description templates with `{workspace}` and `{items}` fields.

## Item visibility and ownership state

`[items] visibility = "feature"` is the default. Claims live only on their
feature line, with no Kata bookmark, until integration.

`[items] visibility = "shared"` publishes new claims through a bookmarked
anchor inside the default tree, so later work based on default sees active
claim markers. Bare `start` never creates an anchor.

Kata keeps no private claim ledger. A driver derives ownership from the base
and revision context supplied by Kata. Shared ownership requires all visible
evidence: the bookmark is the feature/default common fork, the driver derives
the owned items there, and the description matches the configured claim
message. Bookmark existence alone is not ownership evidence.

The bundled Kanban driver is optional and never inferred from a ticket-tree
layout. Use `start` when `[items].driver` is absent.

## Provisioning

Provisioning is disabled unless `provision_hook` names an executable. Kata runs
it with the created workspace path after creation, after any claim establishes
visible ownership. A failed hook leaves the workspace and claim intact for
inspection and repair; stderr markers bracket the hook's output.

## Hosts and requirements

Lifecycle commands require Python 3.11+, jj 0.43.0+, and a POSIX host. The
read-only Kanban subcommand remains portable.

Each supported host registers the read-only session-orientation hook. Worktree
bridges are repository opt-ins; their registration and current host support are
documented in the plugin-root [README](../../../README.md).
