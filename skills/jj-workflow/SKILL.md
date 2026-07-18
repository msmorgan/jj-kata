---
name: jj-workflow
description: Use when working in a jj (Jujutsu) repo that uses the jj-workflow toolkit — feature workspaces with a claim/start → work → integrate lifecycle, a config-based trunk-immutability guard, and conflict tooling. Signs a repo uses it are a `default` coordinator workspace with sibling feature workspaces, a `jjworkflow.toml`, or `scripts/workflow` in the repo.
---

# jj-workflow

The `workflow` and `conflicts` commands are on PATH (this plugin's `bin/`); repos
with a local install expose the same tools as `scripts/workflow` and
`scripts/conflicts`. Every command targets the jj workspace you run it FROM —
its repo, its lock — so always `cd` into the workspace you mean.

Key rules:

- Run `jj` directly; trunk immutability is enforced by a repo-config
  `immutable_heads()` alias, not a wrapper. Never run `git` (blocked by the
  guard hook), and never pass `--config`/`--config-file`/`--ignore-immutable`
  (they bypass the guard and are blocked too).
- Each feature = `workflow claim NAME` (ticketed) or `workflow start NAME`
  (ad-hoc), run from the `default` coordinator workspace → work in the NAME
  workspace (default: a sibling dir; see `workspace_dir` in jjworkflow.toml) →
  `workflow integrate NAME` back on the coordinator. Integrate KEEPS the
  workspace, parked on the integrated tip; the default next step is
  `workflow drop NAME` to retire it so the directory doesn't dangle (keep it
  only for follow-up work). Drop refuses if un-integrated work remains —
  `--force` discards.
- Before any review step, get current with trunk: run `workflow refresh`
  (no argument) from inside the feature workspace — it detaches the stack onto
  the trunk tip; `integrate` re-joins the claim.
- Recover a shifted or divergent feature workspace with `workflow repair`,
  run from inside it. Walk conflicts with `workflow resolve`.
- A workspace created through EnterWorktree (WorktreeCreate hook) is a normal
  feature workspace — the hook claims the matching ticket if the worktree name
  names one. Finish by committing (`jj commit -m`), then `workflow integrate
  NAME` from the coordinator — the workspace survives, so exit the worktree
  choosing "remove" and the hook's plain drop cleans it up. Removing a
  worktree that still holds un-integrated work is refused (workspace and
  commits kept), never silently discarded.
- Resolve alphabetized-list conflicts with `conflicts auto`; inspect any
  conflict with `conflicts show`; pick a side per file with
  `conflicts accept FILE snapshot|diff|base|stack`.
- If the repo hasn't been set up yet (no `immutable_heads()` alias in
  `jj config list --repo`), run the /jj-workflow:setup skill first.
