---
name: jj-workflow
description: Use when working in a jj (Jujutsu) repo that uses the jj-workflow toolkit — feature workspaces with a claim/start → work → integrate lifecycle, a config-based trunk-immutability guard, and conflict tooling. Signs include a `default` coordinator with jj feature workspaces, a `jjworkflow.toml`, or `scripts/workflow`.
---

# jj-workflow

The toolkit is two executables that ship inside this skill:

- `scripts/workflow` — the claim → work → integrate feature lifecycle
- `scripts/conflicts` — conflict inspector and resolver

**Both paths are relative to this skill's own directory** — the directory this
`SKILL.md` was loaded from, not the project you are working in. That is the only
place they live. Nothing is on PATH; call them by absolute path:

```
<skill dir>/scripts/workflow status
```

Every command targets the jj workspace you run it FROM — its repo, its lock — so
`cd` into the workspace you mean and invoke the tool by its absolute path; never
`cd` to the skill directory.

Key rules:

- **NEVER pipe a `workflow` command into `tail`/`head`/`grep`/`less` or any
  other command.** The workflow's exit status is load-bearing, and the four codes
  are distinct on purpose — 0 success; 2 refusal, declined before touching
  anything (bad arguments, wrong workspace, a merge `default@`, a feature behind
  trunk, un-integrated work at `drop`); 69 **expected stop**, a conflict or an
  unclosed `@` left in the workspace for you to fix; 75 lock timeout — and a
  pipe replaces it with the downstream command's
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
  (ad-hoc), run from `default` → work in the NAME workspace
  (`.workspaces/NAME` inside the repo; `workspace_dir` in `jjworkflow.toml`
  overrides the base) →
  finish it with `workflow integrate` (NO name) from INSIDE that workspace, or
  `workflow integrate NAME` from `default`. Self-integrate reaches into
  `default` internally to advance trunk; the immutability alias makes that the
  only context where the default line is writable, so a mis-targeted run
  refuses rather than corrupts. Integrate KEEPS the workspace, parked on the
  integrated tip; the default next step is `workflow drop NAME` — from
  `default` or via ExitWorktree, never from the workspace itself (that would
  delete its own cwd) — to retire it so the directory doesn't dangle (keep it
  only for follow-up work). Drop refuses if un-integrated work remains —
  `--force` discards. To clear a backlog of forgotten directories, `workflow
  drop --integrated` sweeps every integrated, empty workspace at once (skips
  un-integrated ones and any resumed with new work; `--dry-run` previews).
- **The ticket lifecycle belongs to the toolkit, not to you.** `claim` moves the
  ticket `<triage>/` → `wip/` inside the claim commit; `integrate` moves it
  `wip/` → `done/` and records that as the trailing `complete SLUG` commit. Those
  two commits are the ledger — `claim SLUG` opens the record, `complete SLUG`
  closes it. **Never move a ticket out of `wip/` yourself.** If you do, `integrate`
  finds no move left to make, skips the completion commit, and trunk keeps a
  `claim` that never closes; it therefore **refuses (exit 69)** when a ticket the
  claim owns is no longer in `wip/`. Put the file back where it was
  (`mv docs/tickets/done/SLUG.md docs/tickets/wip/SLUG.md`, then `jj squash` to
  fold the correction into the commit that moved it) and re-integrate. The gate is
  **"still in `wip/`"**, not "moved to `done/`" — moving the ticket back to a
  triage folder to hand it back is refused just the same, and integrating it would
  file a ticket you never finished; that case is `drop --amend-ticket` (next
  bullet), which reads the ticket wherever it sits, so the move was never needed.
  Editing a wip ticket's *contents* while you work is fine — only moving or
  deleting the file is banned.
- **A claim that turns out to be undoable ends with `drop --amend-ticket`, never
  with `integrate`.** When the work is impossible, blocked, or premature, write
  why into the wip ticket (a `needs:` line, an explanation), then run
  `workflow drop --amend-ticket NAME` from `default`: it retires the workspace and
  writes those edits back to the ticket in the triage folder it came from, as a
  `tickets: update SLUG` commit. Integrating instead would file the ticket into
  `done/` and book work that never happened. Work outside `docs/tickets/` still
  blocks the drop (add `--force` to discard it along with the workspace).
- Fold extra tickets in place: from a feature workspace, `workflow claim TODO...`
  (no `--into`) folds each into THIS workspace's own claim, accreting its
  description to `claim a, b`. The `--into NAME` form stays coordinator-only.
- Before any review step, get current with trunk: run `workflow refresh`
  (no argument) from inside the feature workspace — it detaches the stack onto
  the trunk tip; `integrate` re-joins the claim. `refresh` owns feature-vs-trunk
  conflicts; `integrate` assumes a clean, already-refreshed feature.
- **A conflicting `refresh` is routine, not a broken state** — it is what trunk
  moving while you work looks like, and it belongs to the ordinary lifecycle.
  Run `workflow resolve` from inside the workspace: it walks the conflicted
  stack **oldest-first**, rebasing each resolution forward, so a single edit
  often clears several commits at once. Do NOT hand-resolve at the tip — jj
  prints its own `jj new` / `jj squash` recipe right above the toolkit's, and
  following it fixes the commit you happen to be standing on while leaving
  older ones in the stack conflicted. Re-run `resolve` until it exits 0, then
  re-run the command that stopped. Keep `repair` for genuinely wrong state.
- Preconditions refuse cleanly rather than doing something surprising:
  **P1** — `refresh`, `integrate`, and `start` refuse when `default@` is a merge
  ("default@ is a merge; the coordinator line must be linear"); abandon or resolve
  the merge on `default` first. **P2** — `integrate` refuses (exit 2) unless the
  feature already sits on the *current* trunk tip; run `workflow refresh` inside
  the workspace first, then integrate. **P4** — `integrate` refuses (exit 69) when
  a ticket the claim owns is no longer in `wip/` (see the ticket-lifecycle rule
  above). All are checked before anything is rewritten, so a refusal leaves the
  workspace exactly as you had it.
- **Close your work before integrating.** `integrate` refuses (exit 69) unless the
  workspace's `@` is an EMPTY, undescribed change — it folds only commits you
  closed yourself and never promotes the working copy for you. End on `jj commit
  -m …` (or `jj describe -m …` then `jj new`). Work still in `@`, undescribed work,
  and a described-but-empty `@` all stop it; nothing is rewritten, fix the working
  copy and re-run.
- **A STALE workspace is skipped, not fixed and not blocking.** Before rewriting
  the shared line the toolkit banks every workspace; one that is already stale
  can't be banked (jj declines) and must not be un-staled (that snapshots its
  edits against the stale operation, forks the op log, and diverges it while
  replacing its files). So it is left exactly as found and the command carries
  on — a long-parked workspace never blocks `integrate`. It prints a `note —
  leaving N stale workspace(s) untouched`; run `workflow repair` there when you
  next work in one.
- **If a command ends with `WARNING — this operation left N DIVERGENT
  change(s)`,** a jj command ran in another workspace while this one was
  rewriting the shared line — their `jj st` snapshotted that workspace's
  working-copy change at the same moment it was being rebased, and jj's reconcile
  left two successors. The flock can't prevent this; a command you don't control
  isn't serializable. Your work DID land — don't re-run. Run `workflow repair` in
  the affected workspace to converge them.
- On working-copy **divergence** or other genuinely wrong state (a stale
  workspace after a concurrent op), run `workflow repair` yourself from inside
  the feature workspace and reason through it step by step — this is
  **agent-initiated**; the toolkit does NOT auto-run repair, it only surfaces the
  stop. `repair` = one-stop recovery (update-stale + converge if divergent +
  resolve if conflicted). Like `resolve` above, it drops you onto the
  conflict and prints the exact conflict-marker locations as
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
- **`workflow status` answers "where am I" in one line** — which workspace,
  what `@` holds, how much is un-integrated, plus conflict/stale/handoff flags.
  Read-only, runs from anywhere. In Claude Code the plugin reports it
  automatically at session start and after each batch of tool calls — but between
  batches only when something structural moved, so a line that does NOT appear
  means nothing changed, not that nothing was checked. Run it by hand after a
  `cd` between workspaces, or any time you are about to act on an assumption
  about where you are.
- **A `HANDOFF.md` in any workspace means work was paused there mid-flight and
  left a resume doc.** `workflow handoffs` scans every workspace for one
  (read-only, runs from anywhere; exit 0 = found, 1 = none). Run it when picking
  up unfamiliar state, and use the /jj-workflow:handoff skill for both halves —
  writing one, and resuming from one (it is burn-after-reading: delete the doc
  once you commit to resuming). Never adopt a handoff without asking the user
  first, unless they already told you to resume from it.
- If the repo hasn't been set up yet (no `immutable_heads()` alias in
  `jj config list --repo`), run the /jj-workflow:setup skill first.
