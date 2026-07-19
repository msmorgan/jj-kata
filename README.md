# jj-workflow

A toolkit for multi-workspace [Jujutsu (jj)](https://github.com/jj-vcs/jj) development.
It enforces trunk immutability through repo config (no wrapper), and manages a
claim→integrate feature lifecycle where each in-flight feature lives in its own
isolated workspace.

---

## Table of contents

1. [Installation](#installation)
2. [Repository shape](#repository-shape)
3. [Trunk immutability (repo config)](#trunk-immutability-repo-config)
4. [The `jj_guard` hook (AI-agent enforcement)](#the-jj_guard-hook)
5. [Feature workflow](#feature-workflow)
   - [Claim / start](#claiming-and-starting-features)
   - [Integrate](#integrating-a-feature)
   - [Drop](#dropping-a-feature)
   - [Refresh](#refreshing-keeping-current-with-trunk)
6. [Ticket folders as status](#ticket-folders-as-status)
7. [Recovery (repair / converge / resolve)](#recovery)
8. [Conflicts tool](#conflicts-tool)
9. [Configuration](#configuration)
10. [Appendix: Example provision-workspace hook](#appendix-example-provision-workspace-hook)

---

## Installation

### As a Claude Code plugin (recommended)

```
/plugin marketplace add msmorgan/jj-workflow
/plugin install jj-workflow@jj-workflow
```

This puts `workflow` and `conflicts` on the Bash tool's PATH (`bin/`), registers
the PreToolUse guard hook automatically (it activates only inside jj repos), and
ships the usage skill. Then, once per repo, run `/jj-workflow:setup` — it sets
the `immutable_heads()` repo-config alias (the actual trunk protection, which is
per-repo state a plugin can't carry) and walks the optional config. Every
command targets the jj workspace you run it from, so one global copy serves all
repos and workspaces. Use `--scope project` on install to enable it for one
repo/team instead of globally. Setup can also wire Claude Code's EnterWorktree
isolation (background sessions, worktree-isolated subagents) to jj-workflow
workspaces via per-repo `WorktreeCreate`/`WorktreeRemove` hooks — isolation then
creates a real feature workspace and removal maps to plain `workflow drop`
(dropping only integrated or untouched workspaces; un-integrated work is kept).

### As a Codex plugin

```bash
codex plugin marketplace add msmorgan/jj-workflow
codex plugin add jj-workflow@jj-workflow
```

Start a new Codex thread after installation so its skills, hooks, and command
aliases are loaded. The plugin provides the `$jj-workflow:jj-workflow` and
`$jj-workflow:setup` skills, puts `workflow` and `conflicts` on the shell
`PATH`, and bundles the repo-aware `PreToolUse(Bash)` guard. Open `/hooks` once
to review and trust the guard; Codex intentionally does not trust executable
plugin hooks merely because the plugin was installed.

Then invoke `$jj-workflow:setup` once per jj repo. It installs the repo-local
`immutable_heads()` alias, which is the actual trunk protection. Optionally set
`JJ_EDITOR=false` for Codex shell commands in the trusted repo's
`.codex/config.toml`:

```toml
[shell_environment_policy]
set = { JJ_EDITOR = "false" }
```

Codex does not provide Claude Code's `EnterWorktree`/`WorktreeRemove` hook
events. Use `workflow claim NAME` or `workflow start NAME` to create isolated
jj workspaces instead.

### Repo-local (no Claude Code required)

```bash
# Symlink mode — updates to jj-workflow propagate to your repo automatically.
./install.fish /path/to/your/repo

# Copy mode — independent copies; upgrade by re-running.
./install.fish --copy /path/to/your/repo
```

This installs into `your-repo/scripts/`:

```
scripts/
  workflow                    ← claim/integrate lifecycle manager
  conflicts                   ← conflict inspector + resolver
  todo                        ← ticket dependency graph
  hooks/
    jj_guard.fish             ← Claude Code PreToolUse guard
  lib/
    setup.fish                ← shared sourcing helpers
    todo_graph.pl             ← dependency graph engine
```

It also sets the repo-config `immutable_heads()` alias that protects the trunk line
(see [Trunk immutability](#trunk-immutability-repo-config)).

**Manual follow-ups after install:**

1. Register `scripts/hooks/jj_guard.fish` as a Claude Code PreToolUse(Bash) hook in
   `.claude/settings.json`, and set env `JJ_EDITOR=false` there (see
   [The jj_guard hook](#the-jj_guard-hook)).
2. Copy `jjworkflow.example.toml` → `jjworkflow.toml` and edit if defaults don't fit.
3. Add a `scripts/provision-workspace` executable if new workspaces need shared or
   generated directories (see [Appendix](#appendix-example-provision-workspace-hook)).
4. Optional, for repos where Claude Code background sessions run: register
   `scripts/hooks/worktree_create.fish` / `worktree_remove.fish` as
   `WorktreeCreate`/`WorktreeRemove` hooks in `.claude/settings.json` (this repo's
   own settings file is the template) — EnterWorktree then creates jj-workflow
   feature workspaces instead of git worktrees. Per-repo only: registered
   globally these hooks would hijack EnterWorktree in plain-git repos. Note when
   ending such a session: `ExitWorktree`'s git-native pre-remove check can't read
   a jj workspace and refuses with "could not verify worktree state" — call it
   with `discard_changes: true`. That only skips the bogus git gate; it does not
   force-discard, because the `WorktreeRemove` hook's *non-force* `workflow drop`
   is still the real gate and keeps any un-integrated work.

---

## Repository shape

The toolkit expects one `default` workspace (the coordinator) plus any number of feature
workspaces, by default each a sibling directory at the same level:

```
~/code/myproj/
  myproj/           ← coordinator (the `default` workspace); run scripts/workflow from here
  feature-a/        ← feature workspace (created by claim/start)
  feature-b/
```

The coordinator's **workspace name** is always `default` (jj's initial workspace), but
its **directory name** is yours to choose — pick it when you clone/init, and name it
after the project (as above) so IDEs and agents see a unique root instead of yet another
`default/`. Nothing hardcodes a `../default` path: scripts resolve the coordinator with
`jj workspace root --name default`. Feature workspace directories are created by the
toolkit and always match their workspace name (`../NAME` by default). Set
`workspace_dir` in `jjworkflow.toml` to put them somewhere else — relative paths
resolve against the repo root, absolute paths are used as-is. If it points inside the
repo (e.g. `.claude/worktrees`), **gitignore that directory**, or jj will snapshot
every child workspace into the coordinator's working copy.

Workspace directories are transient, but only `drop` deletes them: `integrate`
keeps the workspace (its working copy parked on the integrated tip, ready for
follow-up work), and running `drop NAME` afterward is the default next step —
it retires the workspace so the directory doesn't dangle. Keep the workspace
around only when you have follow-up work for it. Plain `drop` refuses a
workspace with un-integrated work; `drop --force` discards it (the commits stay
recoverable via the op log until gc). Nothing is archived.

---

## Trunk immutability (repo config)

Immutability lives in **one shared repo-config alias**, not a wrapper. `install.fish`
sets it:

```toml
# .jj/repo config (jj config set --repo)
revset-aliases.'immutable_heads()' = "builtin_immutable_heads() | (default@ ~ @)"
```

The trick is that `@` resolves **per workspace**, so this single alias yields different
protection depending on where jj runs:

- **In a feature workspace**, `@` is that feature's working copy, so `default@ ~ @`
  reduces to `default@`. Its ancestors — the whole trunk line plus every claim commit —
  become immutable. jj refuses, per-operation, any rebase/abandon/squash that would
  reach shared history or another feature. Your own feature work (commits above your
  claim, not ancestors of `default@`) stays freely rewritable.
- **In the `default` coordinator**, `@` *is* `default@`, so `default@ ~ @` is empty and
  the alias falls back to `builtin_immutable_heads()` (trunk only). The claim commits
  above trunk stay mutable, so a human coordinator can always go in and fix things.

Because the mechanism is native jj config, you invoke `jj` directly from any
workspace — no wrapper, no `-R` pinning. Scripts pass `-R <dir>` explicitly only when
they address *another* workspace. The `--config`, `--config-file`, and
`--ignore-immutable` flags would each bypass this alias; the `jj_guard` hook refuses
them (see below).

---

## The `jj_guard` hook

`scripts/hooks/jj_guard.fish` is a Claude Code `PreToolUse(Bash)` hook that keeps an AI
agent from stepping outside the immutability model. It enforces two bans:

- **`git` is banned outright.** This is a jj repository; git mutations corrupt or
  confuse the op log and working-copy state. (`jj git push` and friends are fine —
  there `git` follows `jj`, not at a command position.)
- **jj with a guard-bypassing flag is refused** — `--config`, `--config-file`, or
  `--ignore-immutable`. Each would override the repo's `immutable_heads()` alias.

Bare `jj` is allowed; immutability is enforced by config, not by routing.

Matching is shell-quote-aware, so these strings are *data*, not commands, and pass
through: `jj describe -m 'see; git blame for context'`, `jj commit -m 'use --config
to override'`, `jj diff --git`. Quote/backslash evasion still fails closed — `"git"
status`, `jj --'config' …`, and a `git`/`--config` hidden in `$(…)` (even inside
double quotes) are all still refused.

Register it in `.claude/settings.json`, and set `JJ_EDITOR=false` so a stray
editor-opening command can't hang the agent (the toolkit always passes `-m`):

```json
{
  "env": { "JJ_EDITOR": "false" },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "fish \"$CLAUDE_PROJECT_DIR/scripts/hooks/jj_guard.fish\"" }
        ]
      }
    ]
  }
}
```

Exit 2 from the hook blocks the tool call with the error on stderr; exit 0 allows it.

---

## Feature workflow

`scripts/workflow` manages the full feature lifecycle under a **two-tier** rule
for *where* each command runs:

- **The `default` coordinator** owns creation and cross-feature ops — `start`,
  `claim NAME`, `drop NAME`, and any `integrate NAME` / `claim … --into NAME` that
  names a *sibling* workspace. These spin up workspaces or rewrite the shared
  trunk line on another workspace's behalf, so they must run from `default`.
- **A feature workspace acts on *itself only*.** From inside it you can `refresh`,
  `claim` (fold more tickets into its own claim), and `integrate` — each targeting
  that very workspace, with no `cd` back to `default`. `repair`, `converge`, and
  `resolve` likewise run from the affected feature workspace. Naming a *sibling*
  from a feature workspace is refused (it would hold the wrong lock).

A mutating command defaults to the workspace you stand in; a positional `NAME` is
honored only from `default` (or when it equals the workspace you're in).
Self-integrate reaches into `default`'s context internally (via `jj -R`) to
advance trunk — and because the `immutable_heads()` alias makes the default line
writable *only* from `default`'s own context, a mis-targeted rewrite refuses
rather than corrupts.

> **Never pipe a `workflow` command into `tail`, `head`, `grep`, `less`, or
> anything else.** Its exit status is load-bearing — `0` success, `2` refusal
> (un-integrated work, an empty/undescribed change), `69` conflict stop, `75`
> lock timeout — and a pipe reports the downstream command's status instead,
> silently masking a refusal or conflict as success. Run it bare and check its
> own exit code; to capture output, redirect to a file (`workflow integrate NAME
> >out.log 2>&1`) rather than piping.

### Claiming and starting features

```bash
# Claim a ticket and spin up a new workspace:
scripts/workflow claim TICKET_NAME

# Start an ad-hoc workspace with no ticket:
scripts/workflow start NAME

# Fold extra tickets into an already-running workspace's claim (from default):
scripts/workflow claim TICKET_A TICKET_B --into NAME

# Same fold, run from INSIDE the feature workspace — folds into ITS own claim,
# no --into and no cd:
scripts/workflow claim TICKET_A TICKET_B
```

`claim TICKET_NAME`:
- Moves the ticket file from its triage folder (`critical/`, `planned/`, or `maybe/`)
  into `docs/tickets/wip/`, inside a new claim commit bookmarked `NAME` on
  `default@`'s linear history.
- Creates the `NAME` workspace directory under the workspace base (`../NAME` by default).
- Runs the provision hook (if configured) to populate shared/generated directories.

`start NAME` does the same without a ticket — useful for exploratory or ad-hoc work.
(Internally `claim` IS `start` + `claim --into`: the workspace primitive and the
ticket-fold primitive compose under one lock hold, so ticket moves have exactly one
mechanism — the fold into the claim commit.)

`claim TICKET_A ... --into NAME` folds extra tickets into an existing workspace's
claim commit. The workspace goes stale (its parent was rewritten); run
`jj workspace update-stale` there before the next commit. Run the *same* fold from
**inside** a feature workspace by dropping `--into` — `claim TICKET_A TICKET_B`
folds those tickets into *that* workspace's own claim (its description accretes to
`claim a, b, …`), no `cd` needed. The `--into NAME` form stays coordinator-only.

**Claim eagerly** — before any exploration, brainstorming, or spec work. This
establishes your baseline and provisions the workspace so builds and tests work
immediately.

### Integrating a feature

```bash
# From INSIDE the feature workspace — integrates THIS workspace (no NAME):
scripts/workflow integrate

# From default — target one workspace by name (unchanged):
scripts/workflow integrate NAME
```

**Preconditions.** `integrate` refuses (exit 2) unless the feature is already
refreshed onto the **current** trunk tip (P2) — if newer non-empty trunk work
sits above it, run `scripts/workflow refresh` inside the workspace first (resolving
any feature-vs-trunk conflict there), then integrate. This is what lets integrate
assume a clean merge: `refresh` owns feature-vs-trunk conflicts, `integrate` does
not. It also refuses if `default@` is a merge (P1 — an ambiguous trunk tip);
linearize the coordinator line first.

`integrate` performs these steps in order:

1. **Refresh + re-join** — detaches the feature stack onto the current trunk tip
   (`default@-`), then re-joins the claim to the now-current feature, rebuilding the
   "claim under `default@`, feature branching off it" shape the fold below relies on.
2. **Fold** — moves `default@` onto the feature tip.
3. **Complete** — moves the owned ticket(s) from `wip/` → `done/` in a final commit.
4. **Park** — drops the claim bookmark (the work is in `default@`'s history now)
   and re-parents the workspace's working copy as a fresh empty change on the
   integrated tip. The workspace and its directory are KEPT — the default next
   step is `workflow drop NAME` to retire it (so the directory doesn't dangle);
   keep it only to resume follow-up work there.

An ad-hoc claim that never adopted a ticket is an empty commit by then — integrate
**elides** it (abandons the empty claim link), so trunk history carries only real
work. Ticketed claims are non-empty (they carry their ticket moves) and stay.

If a conflict arises during the refresh step, integrate stops (exit 69) and leaves the
conflict in place in `../NAME`. Resolve it there and re-run `integrate NAME`.

### Dropping a feature

```bash
# Run from default:
scripts/workflow drop NAME

# Sweep every integrated, empty workspace in one go — the bulk cleanup:
scripts/workflow drop --integrated
scripts/workflow drop --integrated --dry-run   # preview; deletes nothing
```

Retires the workspace and deletes its directory — the default next step after
`integrate NAME`, so the directory doesn't dangle. The plain form is safe by
design: it refuses (exit 2) if the workspace still holds un-integrated work —
only an already-integrated workspace, or an untouched ad-hoc one, is removed.
`drop --force NAME` discards the feature outright: the claim and stack are
abandoned (recoverable via the op log until gc), and the claim commit's
abandonment rolls every owned ticket back to its triage folder automatically.

**`drop --integrated`** is the same safe, plain drop applied to every workspace
at once, for when integrated directories have piled up (agents routinely forget
to clean up after themselves). It removes only workspaces that are **both**
already integrated (their claim bookmark is gone) **and** empty relative to
trunk — never `default`, never the workspace you run it from, never an
un-integrated one, and never an integrated one someone has since resumed work
in (those are reported as kept). It takes no NAME and never force-drops. Add
`--dry-run` to list what it would remove without touching anything.

### Refreshing (keeping current with trunk)

```bash
# From the feature workspace — the common "get review-ready" call (no NAME):
scripts/workflow refresh

# From default, target one workspace by name:
scripts/workflow refresh NAME

# Reorder all non-default workspaces — HUMAN OPERATOR ONLY:
scripts/workflow refresh --all
```

`refresh` has two shapes, by where it runs:

- **From the feature workspace, no NAME (the common case)** — rebases the feature stack
  onto the trunk tip (`default@-`), *detaching* it from its claim commit (which stays
  put in default's line; `integrate` re-joins it). This is the in-place "get current
  before review" call an agent makes; it takes the workspace's own private lock, so it's
  effectively instant.
- **`refresh NAME` from default** — reorders NAME's claim to sit just under `default@`,
  feature carried along (the old behavior).

Both bring the feature current with trunk. A conflict is left in place for you to
resolve — it does not roll back. Always refresh before any review step. Like
`integrate` and `start`, `refresh` refuses (P1) when `default@` is a merge — an
ambiguous trunk tip to rebase onto; linearize the coordinator line first.

> **`refresh --all` is human-only.** It rewrites every workspace's claim at once.
> Never run it as an AI agent: a concurrent `integrate` could fold a stale half into
> `default@`. AI agents touch only their own feature, via `refresh NAME` or
> `integrate NAME`.

---

## Ticket folders as status

Work items are markdown files under `docs/tickets/`, with the folder name as the status:

| Folder | Status |
|--------|--------|
| `critical/`, `planned/`, `maybe/` | Triage — claimable |
| `wip/` | Claimed — in-flight |
| `done/` | Integrated |

Each ticket file can carry `needs:` frontmatter listing dependency slugs. The
`scripts/todo` tool reads that graph without opening individual files:

```bash
scripts/todo ready           # items whose every dependency is in done/ (claimable now)
scripts/todo blocked         # items with at least one unmet dependency
scripts/todo graph SLUG      # upstream deps + downstream blockers for SLUG
scripts/todo check           # detect cycles and dangling dependency references
scripts/todo needs SLUG      # print SLUG's direct needs, one per line
```

Ticket moves happen inside jj commits, so `drop` reverts them automatically:

- `claim`: ticket move is baked into the claim commit → `drop` reverts it.
- `integrate`: ticket move to `done/` is baked into the completion commit.

---

## Recovery

Conflicts and working-copy divergences land in the feature workspace, never on trunk.
Three recovery commands run **from the affected feature workspace**:

> **On any conflict (exit `69`) or divergence, run `repair` (or `resolve`)
> immediately and reason through the conflict step by step.** This is
> **agent-initiated** — the toolkit *never* auto-runs repair; it only stops and
> hands you the workspace. Both commands drop you onto the conflict and print the
> exact conflict-marker locations as `file:line` hits (e.g.
> `…/f.txt:12:<<<<<<< conflict 1 of 2`), so you know precisely which lines to open
> — no whole-file scan. Read those lines, remove every marker, re-run until exit 0.

### `repair` — one-stop recovery

```bash
cd ../NAME
scripts/workflow repair
```

The single entry point for "my branch shifted under me." In order:

1. Clears a stale working copy (`workspace update-stale`).
2. Heals a working-copy divergence if one is detected (`converge`).
3. Walks any refresh/integrate conflicts oldest-first (`resolve`).

**Exit codes:**

| Exit | Meaning |
|------|---------|
| `0` | Branch clean — re-integrate. |
| `1` | Stopped on a conflicted commit. Remove all markers from the files `jj st` lists, then re-run `repair`. |
| `2` | Needs a human — divergent halves hold genuinely different work, or a jj step rolled back. |

When `repair` stops on a conflict it prints each conflict marker's `file:line`
location (matching jj's real markers — `<<<<<<< conflict N of M` … `>>>>>>> …
ends`, seven-or-more brackets), calls `scripts/conflicts show` automatically, and
prints the per-file resolution commands. Read the reported lines directly.

### `converge` — working-copy divergence

```bash
scripts/workflow converge
```

Heals a working-copy divergence: two or more commits sharing `@`'s change ID, left
when a concurrent op rewrote the workspace while it had un-snapshotted edits. Keeps
the half holding your work (identified by content — never by the `/N` index or a
commit hash), drops the rest in one atomic pass.

Refuses when two halves hold genuinely different work — that needs a human
(`jj edit` the right half, `jj abandon` the other).

### `resolve` — conflict walker

```bash
scripts/workflow resolve
```

Walks a feature stack's conflicts oldest-first after `refresh`/`integrate` left them.
Each invocation either:

- Drops you onto the oldest conflicted commit and exits 1 — and prints each
  conflict marker's `file:line` location (`…/f.txt:12:<<<<<<< conflict 1 of 2`) so
  you can Read exactly those lines. Remove every marker from the listed files,
  then re-run.
- Folds your fix into that commit and advances to the next conflict.
- Exits 0 when the stack is clean — re-run `integrate NAME`.

A temporary `NAME-tip` bookmark tracks the real tip while you descend. It is
forgotten on exit 0.

---

## Conflicts tool

`scripts/conflicts` is a fast inspector and resolver for jj's native conflict marker
format (diff+snapshot style).

```bash
scripts/conflicts list                         # list all conflicted files
scripts/conflicts show [FILE ...]              # print conflict hunks with line numbers
scripts/conflicts show --json [FILE ...]       # structured JSON output per hunk
scripts/conflicts accept FILE snapshot         # accept +++ (literal snapshot) side
scripts/conflicts accept FILE diff             # accept %%% (diff-applied) side
scripts/conflicts accept FILE base             # accept the merge base
scripts/conflicts accept FILE stack            # stack both adds: diff first, then snapshot
scripts/conflicts accept FILE stack-snap-first # stack both adds: snapshot first
scripts/conflicts accept FILE sort             # merge alphabetized-list adds, re-sorted
scripts/conflicts auto [--dry-run] [FILE ...]  # auto-merge alphabetized-list conflicts
```

`show --json` includes a `stackable: true` field on hunks where both sides are pure
additions (no deletions) — useful for scripted resolution.

The `auto` subcommand resolves the most common conflict class automatically: when both
branches added lines to an already-sorted list (imports, dependency lists) and the region
is a sorted run of at least 3 lines, it merges both sides' additions and re-sorts — no
manual marker removal. It acts only when confident (both sides pure additions, base run
already sorted); any hunk that does not qualify is reported and left untouched, and `auto`
exits 0 even with hunks left, so it composes into `workflow repair`. Use `--dry-run` to
preview decisions without writing. `accept FILE sort` applies the same merge to one file
on demand.

---

## Configuration

Copy `jjworkflow.example.toml` → `jjworkflow.toml` in your repo root. All keys are
optional; a missing file uses the defaults shown:

```toml
# Executable run after a new workspace is created, with the workspace dir as $1.
# Default: scripts/provision-workspace
provision_hook = "scripts/provision-workspace"
```

> **v1 fixed conventions:** `trunk_workspace` (the trunk workspace name, `default`) and
> `tickets_root` (`docs/tickets`) are fixed in v1 and are not configurable via
> `jjworkflow.toml`. `provision_hook` is the only configurable key. The trunk
> workspace's *directory* name needs no key at all — it is whatever you created it as;
> jj tracks the mapping (see [Repository shape](#repository-shape)).

---

## Appendix: Example provision-workspace hook

When a project has shared gitignored directories each workspace needs — generated build
inputs, large data files, compiled artifacts — create `scripts/provision-workspace`.
The workflow toolkit runs it automatically during `claim`/`start`, passing the new
workspace directory as `$1`. Without a hook, provisioning is a no-op (fine for
source-only projects).

Here is a generic example that symlinks a shared `data/` directory from the coordinator
(default-workspace) checkout:

```sh
#!/usr/bin/env bash
# scripts/provision-workspace
# Called by scripts/workflow claim/start after jj workspace add.
# $1 = the new workspace directory.
set -euo pipefail
ws_dir="$1"
# The coordinator's dir name is not fixed (see Repository shape) — resolve it
# via jj rather than assuming ../default. Pass -R so it addresses the new
# workspace regardless of where the hook is invoked from.
default_dir="$(jj -R "$ws_dir" workspace root --name default)"

# Symlink shared read-only data back to the coordinator checkout.
# The symlink is excluded by .git/info/exclude in the default workspace (shared
# by all secondary workspaces), so no per-workspace exclude is needed.
ln -sfn "$default_dir/data" "$ws_dir/data"

echo "Provisioned: symlinked data/ in $ws_dir"
```

Make it executable:

```bash
chmod +x scripts/provision-workspace
```

The `.gitignore` entry for `data/` should use a **trailing slash** (`data/`) so it
matches the directory but not the symlink — the symlink form stays excluded via
`.git/info/exclude` in the default workspace (which is shared across all secondary
workspaces because they have no `.git` of their own).

Verify a newly provisioned workspace is clean:

```bash
jj st   # must report no changes
```
