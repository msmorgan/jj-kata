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
5. [The status line (`workflow status`)](#the-status-line)
6. [Feature workflow](#feature-workflow)
   - [Claim / start](#claiming-and-starting-features)
   - [Integrate](#integrating-a-feature)
   - [Drop](#dropping-a-feature)
   - [Refresh](#refreshing-keeping-current-with-trunk)
7. [Ticket folders as status](#ticket-folders-as-status)
8. [Handing off an open thread](#handing-off-an-open-thread)
9. [Recovery (repair / converge / resolve)](#recovery)
10. [Conflicts tool](#conflicts-tool)
11. [Configuration](#configuration)
12. [Appendix: Example provision-workspace hook](#appendix-example-provision-workspace-hook)

---

## Installation

### As a Claude Code plugin (recommended)

```
/plugin marketplace add msmorgan/jj-workflow
/plugin install jj-workflow@jj-workflow
```

This ships the usage skill and registers the PreToolUse guard and the
PostToolUse [status line](#the-status-line) automatically (both activate only
inside jj repos).

The executables live in `skills/jj-workflow/scripts/`, beside the skill that
documents them — the skill tells the agent to run `scripts/workflow` and
`scripts/conflicts` relative to its own directory, which is how every other
skill-with-tools works. Nothing is put on PATH, and there is no second copy to go
stale. Then, once per repo, run `/jj-workflow:setup` — it sets
the `immutable_heads()` repo-config alias (the actual protection for trunk and
for features against each other, which is per-repo state a plugin can't carry)
and walks the optional config. Every
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
`$jj-workflow:setup` skills and bundles the repo-aware `PreToolUse(Bash)` guard.
It also reports the status line at `SessionStart` and after each `Write`, `Edit`,
or `Bash` tool, using Codex's `Write`/`Edit` aliases for `apply_patch`.

The two executables are run out of the skill's own directory
(`skills/jj-workflow/scripts/`), exactly as on Claude Code — nothing depends on
Codex exposing a `bin/` field or on a hook firing, so the tools are reachable
the moment the skill loads. Feature workspaces go in the repo's `.workspaces/`,
which is inside Codex's writable sandbox, so nothing needs configuring.

The executable hooks are a separate matter: open `/hooks` once to review and
trust them.
Codex intentionally does not trust executable plugin hooks merely because the
plugin was installed, and until they are trusted neither the git/bypass-flag ban
nor automatic status snapshotting runs there.

Then invoke `$jj-workflow:setup` once per jj repo. It sets the repo-config
`immutable_heads()` alias, which is the actual protection — trunk, and features
from each other. Optionally set
`JJ_EDITOR=false` for Codex shell commands in the trusted repo's
`.codex/config.toml`:

```toml
[shell_environment_policy]
set = { JJ_EDITOR = "false" }
```

Codex does not provide Claude Code's `EnterWorktree`/`WorktreeRemove` hook
events. Use `workflow claim NAME` or `workflow start NAME` to create isolated
jj workspaces instead.

### As a Google Antigravity plugin

Place this repository as a custom `jj-workflow` plugin under either the
workspace's `.agents/plugins/` directory or the global
`~/.gemini/config/plugins/` directory. The root `plugin.json` and `hooks.json`
are Antigravity's native plugin entry points; the same `skills/` and hook scripts
serve all three harnesses.

Antigravity snapshots after `write_to_file`, both replace-file tools, and
`run_command`. Its `PostToolUse` event cannot inject model context directly, so
the hook stores a changed line there and delivers it as an ephemeral message at
the next `PreInvocation`. Invocation zero supplies the session-orientation line.

---

## Repository shape

The toolkit expects one `default` workspace (the coordinator) plus any number of
feature workspaces, which live in `.workspaces/` inside the repo:

```
myproj/                 ← coordinator (`default`)
  .workspaces/
    feature-a/          ← feature workspace
    feature-b/
```

In-repo because that is the one place every host can write — a sandboxed agent
host (Codex and friends) exposes the repo root and little else, so a base outside
the repo is simply unavailable there. The toolkit keeps `.workspaces/` invisible
to jj by putting a `.gitignore` holding `*` **inside it**, which ignores the
directory's whole contents including that file. Nothing to add to your repo's
own `.gitignore`, and no setup step to forget.

The coordinator's **workspace name** is always `default` (jj's initial workspace), but
its **directory name** is yours to choose — pick it when you clone/init, and name it
after the project (as above) so IDEs and agents see a unique root instead of yet another
`default/`. Nothing hardcodes a `../default` path: scripts resolve the coordinator with
`jj workspace root --name default`. Feature workspace directories are created by the
toolkit and always match their workspace name (`.workspaces/NAME`). Set
`workspace_dir` in `jjworkflow.toml` to override the base — relative paths
resolve against the repo root, absolute paths are used as-is, and `".."` gives
you the sibling layout. Any base inside the repo gets the same self-ignore
treatment; a base outside it needs none.

Workspace directories are transient, but only `drop` deletes them: `integrate`
keeps the workspace (its working copy parked on the integrated tip, ready for
follow-up work), and running `drop NAME` afterward is the default next step —
it retires the workspace so the directory doesn't dangle. Keep the workspace
around only when you have follow-up work for it. Plain `drop` refuses a
workspace with un-integrated work; `drop --force` discards it (the commits stay
recoverable via the op log until gc). Nothing is archived.

---

## Trunk immutability (repo config)

Immutability lives in **shared repo-config aliases**, not a wrapper. `/jj-workflow:setup`
sets them:

```toml
# .jj/repo config (jj config set --repo)
# all_if_any(rev) resolves to all() if `rev` contains any changes, else none()
revset-aliases.'all_if_any(rev)' = "descendants(ancestors(rev))"
revset-aliases.'immutable_heads()' = "builtin_immutable_heads() | ((working_copies() ~ @) & all_if_any(default@ ~ @))"
```

The trick is that `@` resolves **per workspace**, so this one rule yields different
protection depending on where jj runs:

- **In a feature workspace**, `@` is that feature's working copy, so `default@ ~ @`
  reduces to `default@`. Its ancestors — the whole trunk line plus every claim commit —
  become immutable, and `working_copies() ~ @` adds every *sibling* feature's working
  copy. jj refuses, per-operation, any rebase/abandon/squash that would reach shared
  history or another feature. Your own feature work (commits above your claim, not
  ancestors of `default@`) stays freely rewritable.
- **In the `default` coordinator**, `@` *is* `default@`, so `default@ ~ @` is empty —
  which collapses the whole gated term — and the alias falls back to
  `builtin_immutable_heads()` (trunk only). Feature working copies stay mutable here,
  which is exactly what lets `integrate`, `refresh`, and `drop` rewrite a feature's
  stack from the coordinator. The claim commits above trunk stay mutable too, so a
  human coordinator can always go in and fix things.

`all_if_any` is an emptiness test, not a traversal: `root()` is an ancestor of every
commit, so `descendants(ancestors(rev))` lifts a non-empty `rev` to `all()` while an
empty one stays `none()`. That turns "am I the coordinator?" into a gate the `&` can
read. The lift is
what makes sibling protection possible — sibling working copies are *disjoint* from
`default@`, so a plain `& (default@ ~ @)` would filter them out in both contexts
instead of gating them, leaving you with trunk protection and nothing more.

Because the mechanism is native jj config, you invoke `jj` directly from any
workspace — no wrapper, no `-R` pinning. Scripts pass `-R <dir>` explicitly only when
they address *another* workspace. The `--config`, `--config-file`, and
`--ignore-immutable` flags would each bypass this alias; the `jj_guard` hook refuses
them (see below).

---

## The `jj_guard` hook

`hooks/jj_guard.fish` is a Claude Code `PreToolUse(Bash)` hook that keeps an AI
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

**The plugin registers it for you**; it activates only inside jj repos. Also set
`JJ_EDITOR=false` so a stray editor-opening command can't hang the agent (the
toolkit always passes `-m`) — `"env": {"JJ_EDITOR": "false"}` in
`.claude/settings.json`, or `[shell_environment_policy]` in Codex's
`.codex/config.toml`.

Exit 2 from the hook blocks the tool call with the error on stderr; exit 0 allows it.
The hook only ever *decides* — it never rewrites the command it was handed, and
nothing about reaching the toolkit's own executables depends on it running.

---

## The status line

`workflow status` prints one line describing where the current workspace stands —
the thing a human gets for free from a shell prompt, and an agent otherwise has to
go ask for:

```
jj: default | @ szznvzyrxylx (empty)
jj: feat-login | @ qpvxwlkmrytu "wip: session cookie" +220/-74 (+4/~1/-1) | 3 unintegrated
jj: feat-login | @ snwwkymxzmyw (empty) | 1 unintegrated | ⚠ 2 conflicted
jj: feat-login | ⚠ STALE working copy — run `workflow repair` before trusting anything here
```

Field order is decision order. *Which workspace* decides which commands are even
legal; then what `@` holds (`(empty)` / `(no desc)` / its description, plus line
counts and file counts by kind); then how many changes trunk does not have yet —
the number that says whether `integrate` would do anything. The `⚠` fields appear
only when non-zero, so a normal line stays short and an abnormal one is hard to
skim past. It runs from any workspace, reads only, and takes the workflow lock
briefly so it never reports a state caught mid-rewrite.

Two things are deliberately absent. The **operation id** — every command that
consumes one (`undo`, `redo`, `op restore`) is the human operator's, so printing
it to an agent is a token it can never act on. And **bookmarks**, except when one
sits on `@` itself, which is worth a warning because an edit there moves shared
state.

### As a hook

`hooks/jj_status.fish` reports that line to an agent
at session orientation and after each write, update, or shell tool. **The plugin
registers it for you** — there is nothing to add to a settings file.

The two moments cover opposite ends of the same problem. **Session orientation**
is when an agent knows nothing about where it is, so the line reports there
unconditionally. Claude Code and Codex provide `SessionStart`; Antigravity uses
invocation zero because its hook API has no equivalent event. This is also when
the hook sweeps suppression caches left by sessions over a week old.

**`PostToolUse`** fires immediately after each relevant tool completes. Claude
Code uses `Write`, `Edit`, and `Bash`; Codex maps `apply_patch` to the
`Write`/`Edit` aliases and unified exec to `Bash`; Antigravity uses
`write_to_file`, `replace_file_content`, `multi_replace_file_content`, and
`run_command`. The status command takes the workflow lock, so hooks completing
from parallel tools serialize their snapshots instead of racing jj's shared
operation log.

The hook deliberately separates checking from speaking:

- **Every registered tool runs the status probe.** This eagerly snapshots file
  writes and updates instead of leaving them only on disk until a later jj
  command. Shell calls stay broad because arbitrary commands can change files.
- **It speaks only when the rendered line changed.** Edit statistics are part of
  that line, so changed volume re-arms the report; a byte-for-byte repeat remains
  silent even though the snapshot check still ran.

Antigravity's `PostToolUse` output contract accepts only `{}`, so that event
stores a changed line in `.jj/`; the following `PreInvocation` injects it as an
ephemeral message. Claude Code and Codex accept the changed line directly as
`PostToolUse` additional context.

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
> anything else.** Its exit status is load-bearing, and the four codes are
> distinct on purpose — `0` success; `2` refusal, declined before touching
> anything (bad arguments, wrong workspace, a merge `default@`, a feature behind
> trunk, un-integrated work at `drop`); `69` **expected stop**, a conflict, an
> unclosed working copy, or a hand-moved ticket left in the workspace for you to
> fix; `75` lock timeout.
> A pipe reports the downstream command's status instead,
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
- Moves the ticket file from its triage folder (`bugs/`, `critical/`, `planned/`, or `maybe/`)
  into `docs/tickets/wip/`, inside a new claim commit bookmarked `NAME` on
  `default@`'s linear history.
- Creates the `NAME` workspace directory under the workspace base (`../NAME` by default).
- Runs the provision hook (if configured) to populate shared/generated directories.

`start NAME` does the same without a ticket — useful for exploratory or ad-hoc work.
(Internally `claim` IS `start` + `claim --into`: the workspace primitive and the
ticket-fold primitive compose under one lock hold, so ticket moves have exactly one
mechanism — the fold into the claim commit.)

`claim TICKET_A ... --into NAME` folds extra tickets into an existing workspace's
claim commit. The operation snapshots every workspace before rewriting the shared
line and reconciles their pointers afterward. Run the *same* fold from
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

It further refuses (exit 69) unless the workspace's `@` is an **empty, undescribed**
change — the shape you get by ending on `jj commit` or `jj new`. Integrate folds
only commits you closed yourself; it never promotes the working copy for you. Three
states stop it: work still sitting in `@` **described** (run `jj new` to cap it),
work sitting there **undescribed** (`jj describe -m …`, then `jj new`), and an
`@` that is described but empty (a set-up-but-unfilled commit — finish it, or clear
the description / abandon it). Nothing is rewritten in any of these cases; fix the
working copy in the workspace and re-run.

`integrate` performs these steps in order:

1. **Refresh + re-join** — detaches the feature stack onto the current trunk tip
   (`default@-`), then re-joins the claim to the now-current feature, rebuilding the
   "claim under `default@`, feature branching off it" shape the fold below relies on.
2. **Fold** — moves `default@` onto the feature tip.
3. **Complete** — moves the owned ticket(s) from `wip/` → `done/` in a final
   `workflow: complete SLUG` commit.
4. **Park** — drops the claim bookmark (the work is in `default@`'s history now)
   and re-parents the workspace's working copy as a fresh empty change on the
   integrated tip. The workspace and its directory are KEPT — the default next
   step is `workflow drop NAME` to retire it (so the directory doesn't dangle);
   keep it only to resume follow-up work there.

An ad-hoc claim that never adopted a ticket is an empty commit by then — integrate
**elides** it (abandons the empty claim link), so trunk history carries only real
work. Ticketed claims are non-empty (they carry their ticket moves) and stay.

**Never move a ticket out of `wip/` yourself** — step 3 is integrate's job, and
the `workflow: claim SLUG` / `workflow: complete SLUG` pair is the ledger that
`jj log -r 'description(glob:"workflow: complete *")'` reads back as shipped work.
A feature that
performs the `wip/` → `done/` move inside its own commit leaves integrate with
nothing left to move, so the completion commit is skipped and trunk keeps a
`claim` that never closes. Integrate therefore **refuses (exit 69, P4)** when a
ticket the claim owns is no longer in `wip/`, naming where it went and how to put
it back (`mv` it back, then `jj squash` to fold the correction into the commit
that moved it).

The gate is **"still in `wip/`"**, not "moved to `done/`" — the other direction is
just as broken and just as common. An agent that decides the claim is undoable and
moves the ticket back to its triage folder by hand, then integrates anyway, files
a ticket it never finished; that is `drop --amend-ticket`'s job, and the refusal
says so (and points out that `--amend-ticket` reads the ticket wherever it sits,
so the manual move was never needed). A deleted ticket is refused too. Editing a
wip ticket's *contents* while you work is fine — only moving or deleting the file
is banned.

If a conflict arises during the refresh step, integrate stops (exit 69) and leaves the
conflict in place in `../NAME`. Run `workflow resolve` there — it walks the conflicted
stack oldest-first — then re-run `integrate NAME`.

### Dropping a feature

```bash
# Run from default:
scripts/workflow drop NAME

# The claim turned out to be undoable — keep the notes, give the ticket back:
scripts/workflow drop --amend-ticket NAME

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

**`drop --amend-ticket NAME`** is the ending for a claim that turns out **not to
be doable** — blocked on something unbuilt, mis-scoped, premature. Write the
reason into the wip ticket (a `needs:` line, an explanation of what has to happen
first), then drop with the flag: the workspace is retired exactly as a plain drop
retires it, and the edits are written back onto the ticket **in the triage folder
it was claimed from** — the same file, at its original path — as a `tickets: amend
SLUG` commit on trunk. A claim owning several tickets sends each one home
to its own folder in a single commit; a census-minted ticket that had no file
before lands in `docs/tickets/planned/`, and the summary line says so.

This exists because the alternative agents reach for is `integrate`, which files
the ticket into `done/` and books work that never happened. The flag rescues only
`docs/tickets/`: work outside it still blocks the drop (exit 2) unless you add
`--force`, and a ticket that came back unedited produces no commit at all rather
than an empty one. A workspace with no claimed ticket (an ad-hoc `start`) is
refused — there is nothing to write back.

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
| `bugs/`, `critical/`, `planned/`, `maybe/` | Triage — claimable |
| `wip/` | Claimed — in-flight |
| `done/` | Integrated |

Each ticket file can carry `needs:` frontmatter listing dependency slugs. The
toolkit's `todo` tool — beside `workflow` in the skill's `scripts/` — reads
that graph without opening individual files:

```bash
todo ready           # items whose every dependency is in done/ (claimable now)
todo blocked         # items with at least one unmet dependency
todo graph SLUG      # upstream deps + downstream blockers for SLUG
todo check           # detect cycles and dangling dependency references
todo needs SLUG      # print SLUG's direct needs, one per line
```

Ticket moves happen inside jj commits, so `drop` reverts them automatically:

- `claim`: ticket move is baked into the claim commit → `drop` reverts it.
- `integrate`: ticket move to `done/` is baked into the completion commit.

Both moves belong to the toolkit. Never move a ticket between folders by hand
inside a feature workspace — `integrate` refuses (exit 69) if you did. To hand a
ticket back with notes instead of finishing it, use `drop --amend-ticket NAME`.

**Every commit the toolkit writes for you is prefixed `workflow:`** — so its
bookkeeping greps apart from the commits you and your agents author:

| command | commit |
|---|---|
| `start NAME` | `workflow: start NAME` |
| `claim A`, `claim A B --into N` | `workflow: claim A, B` |
| `integrate NAME` | `workflow: complete A B` |
| `drop --amend-ticket NAME` | `tickets: amend A, B` |

The last one is deliberately *not* `workflow:` — it is a real edit to a ticket's
contents, not a lifecycle marker, and it is the one toolkit commit that survives
as content rather than as a record of what the toolkit did.

---

## Handing off an open thread

A thread rarely ends exactly when a session does. A **handoff doc** is the
mid-flight save: a `HANDOFF.md` at a workspace root that tells a fresh agent —
one with no memory of the conversation — what is open, what is already settled,
and what it is being asked to hand back.

**A handoff is not always work to deliver.** A discussion you want taken further
by a different model, a call waiting on you, a change nobody has checked, and
context that would be expensive to reconstruct are all handoffs. Every doc
therefore opens with a **Kind**:

| Kind | The next session hands back |
|---|---|
| `build` | a change |
| `discuss` | the question worked up — research, design, options on the table; nothing committed |
| `decide` | a pick among options already framed |
| `review` | a verdict on work already done |
| `park` | nothing; it is a save so the context isn't lost |

The Kind decides what the doc must contain and what the next session may do with
it — a `discuss` carries the question and what's already ruled out and
deliberately has **no** "next step" (writing one presumes the answer), while a
`park` states plainly that nothing is due. Getting it wrong is the most expensive
mistake the doc can make: a `discuss` dressed as a `build` sends an agent off
writing code to answer an unsettled question. An optional **Intended for** line
routes it (`Fable`, the user, `any agent`).

**The existence of the file is the signal.** There is no state to consult and no
flag to set: a workspace holding a `HANDOFF.md` has a thread open in it, and one
without doesn't.

```bash
# From anywhere — read-only scan of every workspace in the repo:
scripts/workflow handoffs
# stdout:  feat-login   /path/to/feat-login/HANDOFF.md
# stderr:  workflow: 2 handoff doc(s): feat-login (build), mirror-api (discuss)
```

Exit status is grep-style — **0** = at least one found, **1** = none — so it is
safe to branch on. It runs from any workspace, takes no lock, and takes no
arguments. stdout is exactly `NAME<TAB>PATH` per hit; the Kind labels go to the
stderr summary, so a coordinator can see which threads are code to finish and
which are a question or a park without opening every doc. A doc written before
Kinds existed reads as `(?)`.

**The doc is deliberately never committed.** It is written into the working-copy
commit (`@`) and left there, which buys three things:

- `jj st` and `jj diff --summary` surface it on every routine status check, so a
  paused workspace announces itself without anyone remembering to look.
- Presence is detected with a plain `test -f`, *not* a diff read. If the doc gets
  committed by accident it still shows up in `handoffs`, and the resume side
  catches the mistake by noticing it is missing from `jj st`.
- A non-empty `@` means `drop --integrated` will not sweep the workspace away —
  paused work survives the bulk cleanup on its own.

Writing one requires an **empty working copy** (commit or abandon loose edits
first, so the doc can describe committed state by change id) and a **real open
thread** — a handoff describing something nobody is carrying is worse than none,
because the next agent will act on it. `park` does not lower that bar: "nothing
is due" is not "nothing happened".

Resuming is **burn-after-reading**: the doc is deleted the moment an agent commits
to taking the thread, before any other step. That returns `@` to clean and empty
and stops a stale doc from misleading whoever comes next. An agent that has not
been told to resume must *ask* first — a handoff often belongs to a different
effort than the session that stumbled onto it, and its **Intended for** line may
name someone else entirely. A `park` is the exception to the burn: reading one is
not taking it, so it stays put until someone converts it into real work.

Both halves are driven by the `handoff` skill (`/jj-workflow:handoff`), which
carries the doc template and the full protocol.

---

## Recovery

Conflicts and working-copy divergences land in the feature workspace, never on trunk.
Three recovery commands run **from the affected feature workspace**:

> Before any command rewrites the shared default line it **banks every
> workspace** — snapshots on-disk edits into each working-copy commit — so the
> rewrite carries them along. A workspace that is already **stale** can't be
> banked (jj declines to snapshot a stale working copy), and un-staling it is
> worse: `update-stale` would snapshot those edits against the stale operation,
> forking the op log into a **divergence** and replacing the workspace's files
> with the other side. So a stale workspace is **left strictly alone** — skipped
> by both the bank and the un-stale that follows the rewrite — and the command
> carries on. A long-parked workspace never blocks `integrate`; run `repair`
> there when you next work in it.
>
> One divergence route remains and is **not preventable** from here: a jj command
> run in another workspace *while* a rewrite is in flight. Their `jj st`
> snapshots that workspace's working-copy change at the same moment it is being
> rebased; both ops descend from one op head and jj's reconcile leaves two
> successors. The flock only serializes `workflow` commands, not everyone's `jj`.
> Mutating commands therefore check afterwards and print `WARNING — this
> operation left N DIVERGENT change(s)` rather than let it pass as success. The
> work landed; run `repair` in the affected workspace.

> **A conflicting `refresh` (exit `69`) is routine, not a broken state** — it is
> what trunk moving while you work looks like. Run `resolve`; keep `repair` for
> genuinely wrong state (staleness, divergence). Either way, act **immediately**
> and reason through the conflict step by step. This is **agent-initiated** — the
> toolkit *never* auto-runs recovery; it only stops and hands you the workspace.
> Note that jj prints its own `jj new` / `jj squash` recipe just above the
> toolkit's message: ignore it. It resolves the commit you happen to be standing
> on, while `resolve` walks the stack **oldest-first** and rebases each
> resolution forward, so a single edit often clears several commits at once.
> Both commands drop you onto the conflict and print the
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

Copy `jjworkflow.example.toml` (beside the setup skill's `SKILL.md`) →
`jjworkflow.toml` in your repo root. All keys are
optional; a missing file uses the defaults shown:

```toml
# Directory that holds feature workspaces. Relative paths resolve against the
# repo root. Default: ".workspaces" (self-ignored by the toolkit). Set ".." for
# the sibling layout. Omit to keep the default; uncomment to override.
# workspace_dir = ".custom/workspaces"

# Executable run after a new workspace is created, with the workspace dir as $1.
# Default: scripts/provision-workspace
provision_hook = "scripts/provision-workspace"

# PROJECT-provided ticket/census helper for claim. Relative to the repo root.
# Omitted, the toolkit's own `todo` (shipped beside `workflow`) is used.
# todo_cmd = "scripts/mytodo"
```

> **v1 fixed conventions:** `trunk_workspace` (the trunk workspace name, `default`) and
> `tickets_root` (`docs/tickets`) are fixed in v1 and are not configurable via
> `jjworkflow.toml`. The trunk workspace's *directory* name needs no key at all
> — it is whatever you created it as; jj tracks the mapping (see
> [Repository shape](#repository-shape)).

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
