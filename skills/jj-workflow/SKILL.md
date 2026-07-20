---
name: jj-workflow
description: Use when working in a jj (Jujutsu) repo that uses the jj-workflow toolkit — feature workspaces with a claim/start → work → integrate lifecycle, a config-based trunk-immutability guard, and conflict tooling. Signs a repo uses it are a `default` coordinator workspace with sibling feature workspaces, a `jjworkflow.toml`, or `scripts/workflow` in the repo.
---

# jj-workflow

The `workflow` and `conflicts` commands are on PATH (this plugin's `bin/`).
In Codex, the plugin's trusted PreToolUse hook prepends that directory to each
shell call because Codex manifests do not provide a native `bin/` field. If
either command does not resolve, stop and ask the user to review and trust this
plugin's hook in `/hooks`; do not substitute repo-local scripts that may be
absent or stale. Repos with a local install expose the same tools as
`scripts/workflow` and `scripts/conflicts`. Every command targets the jj
workspace you run it FROM — its repo, its lock — so always `cd` into the
workspace you mean.

Key rules:

- **NEVER pipe a `workflow` command into `tail`/`head`/`grep`/`less` or any
  other command.** The workflow's exit status is load-bearing — 0 success,
  2 refusal (e.g. un-integrated work, empty/undescribed change), 69 conflict
  stop, 75 lock timeout — and a pipe replaces it with the downstream command's
  status, silently masking a refusal or conflict as success. Run it bare and
  read its own exit code and stderr. If you must capture output, redirect to a
  file (`workflow integrate NAME >out.log 2>&1`) and check `$status`, never pipe.
- Run `jj` directly; trunk immutability is enforced by a repo-config
  `immutable_heads()` alias, not a wrapper. Never run `git` (blocked by the
  guard hook), and never pass `--config`/`--config-file`/`--ignore-immutable`
  (they bypass the guard and are blocked too).
- **Two-tier model.** The `default` coordinator owns creation and cross-feature
  ops — `workflow start NAME`, `workflow claim NAME`, `workflow drop NAME`, and
  any `integrate NAME` / `claim ... --into NAME` naming a *sibling* all run from
  `default`. A **feature workspace acts on itself only**: from inside it you can
  `refresh`, `claim` (self-fold), and `integrate` THIS workspace in place — no
  `cd` back to `default`. Naming a sibling from a feature workspace is refused.
- Each feature = `workflow claim NAME` (ticketed) or `workflow start NAME`
  (ad-hoc), run from `default` → work in the NAME workspace (default: a sibling
  dir; see `workspace_dir` in jjworkflow.toml) → finish it with `workflow
  integrate` (NO name) from INSIDE that workspace, or `workflow integrate NAME`
  from `default`. Self-integrate reaches into `default` internally to advance
  trunk; the immutability alias makes that the only context where the default
  line is writable, so a mis-targeted run refuses rather than corrupts. Integrate
  KEEPS the workspace, parked on the integrated tip; the default next step is
  `workflow drop NAME` — from `default` or via ExitWorktree, never from the
  workspace itself (that would delete its own cwd) — to retire it so the
  directory doesn't dangle (keep it only for follow-up work). Drop refuses if
  un-integrated work remains — `--force` discards. To clear a backlog of
  forgotten directories, `workflow drop --integrated` sweeps every integrated,
  empty workspace at once (skips un-integrated ones and any resumed with new
  work; `--dry-run` previews).
- Fold extra tickets in place: from a feature workspace, `workflow claim TODO...`
  (no `--into`) folds each into THIS workspace's own claim, accreting its
  description to `claim a, b`. The `--into NAME` form stays coordinator-only.
- Before any review step, get current with trunk: run `workflow refresh`
  (no argument) from inside the feature workspace — it detaches the stack onto
  the trunk tip; `integrate` re-joins the claim. `refresh` owns feature-vs-trunk
  conflicts; `integrate` assumes a clean, already-refreshed feature.
- Two preconditions refuse cleanly rather than doing something surprising:
  **P1** — `refresh`, `integrate`, and `start` refuse when `default@` is a merge
  ("default@ is a merge; the coordinator line must be linear"); abandon or resolve
  the merge on `default` first. **P2** — `integrate` refuses (exit 2) unless the
  feature already sits on the *current* trunk tip; run `workflow refresh` inside
  the workspace first, then integrate.
- On ANY conflict (a command exiting 69) or working-copy divergence, immediately
  run `workflow repair` (or `workflow resolve`) yourself from inside the feature
  workspace and reason through the conflict step by step — this is
  **agent-initiated**; the toolkit does NOT auto-run repair, it only surfaces the
  stop. `repair` = one-stop recovery (update-stale + converge if divergent +
  resolve if conflicted); `resolve` walks a conflicted stack oldest-first. Both
  drop you onto the conflict and print the exact conflict-marker locations as
  `file:line` hits (e.g. `…/f.txt:12:<<<<<<< conflict 1 of 2`) — Read those lines,
  remove every marker, then re-run the same command until it exits 0.
- A workspace created through EnterWorktree (WorktreeCreate hook) is a normal
  feature workspace — the hook claims the matching ticket if the worktree name
  names one. Finish by committing (`jj commit -m`), then `workflow integrate
  NAME` from the coordinator — the workspace survives, so exit the worktree
  choosing "remove" and the hook's plain drop cleans it up. ExitWorktree's own
  pre-remove check is git-native and can't read a jj workspace, so it refuses
  with "could not verify worktree state" — call it with `discard_changes: true`
  to get past that (don't waste the first attempt on it). This is safe:
  `discard_changes` only skips that bogus git gate, it does NOT force-discard —
  the actual removal is delegated to the `WorktreeRemove` hook's *non-force*
  `workflow drop`, which drops an integrated/empty workspace (dir deleted) but
  refuses one that still holds un-integrated work (workspace, dir, and commits
  all kept), never silently discarded. To actually throw away un-integrated
  work, ExitWorktree with "keep" (parking the workspace) and then run
  `workflow drop NAME --force` from `default` — only a direct `--force` discards;
  the hook path never can.
- Resolve alphabetized-list conflicts with `conflicts auto`; inspect any
  conflict with `conflicts show`; pick a side per file with
  `conflicts accept FILE snapshot|diff|base|stack`.
- If the repo hasn't been set up yet (no `immutable_heads()` alias in
  `jj config list --repo`), run the /jj-workflow:setup skill first.
