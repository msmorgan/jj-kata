---
needs: []
---

# finish-from-worktree

Let an agent run the **whole feature lifecycle from inside its EnterWorktree
workspace** — fold tickets, refresh, integrate — **without ever `cd`-ing back to
`default`**. Plus two robustness bugs surfaced while designing it.

- **Version:** ship as **0.4.0** (behavior-changing) — single release, bug fixes
  folded in. The actual `.claude-plugin/plugin.json` bump lands with the code, not
  this ticket.
- **Design scratch (gitignored):** `docs/superpowers/specs/2026-07-18-finish-from-worktree-design.md`
  — this ticket is the tracked canonical copy.

## Goal

Today the mutating commands (`claim`, `integrate`, `drop`) refuse anywhere but
the `default` coordinator workspace, so an agent must juggle its cwd. Remove that
juggling while keeping the safety the `default`-only rule bought.

Non-goal: making `integrate` conflict-free. Integration is a real merge; a
feature-vs-trunk conflict is inherent. We *relocate* where it surfaces (to
`refresh`), we do not eliminate it.

## Capability-boundary invariant

- **A feature workspace acts on *itself only*** — plus it may reach into the
  shared **`default`/trunk** line to integrate *itself*. It may **never**
  `integrate`, `drop`, `refresh`, `repair`, `resolve`, `converge`, or `start` a
  **sibling** feature workspace.
- **`default` (coordinator)** is the only place that can name and act on any
  workspace.

Mirrors the invariant the code already has for `refresh` (a feature ws refuses
`refresh NAME` for a foreign NAME, `scripts/workflow:683-685`); generalize it.

## Command surface — before → after

| Command | Today | After |
|---|---|---|
| `start NAME` | `default` only | unchanged (creation is coordinator-owned; EnterWorktree hook is the other creator) |
| `claim NAME` | `default` only | unchanged |
| `claim T --into NAME` | `default` only | from a feature ws: `claim T` folds into *self* (no `--into`, no cd); from `default`: `claim T --into NAME` unchanged |
| `integrate NAME` | `default` only | from a feature ws: `integrate` (no NAME) integrates *self*, reaching into `default` internally; from `default`: `integrate NAME` unchanged; foreign NAME from a feature ws → refused |
| `drop NAME` | `default` only | `default` + ExitWorktree/WorktreeRemove only. A feature ws never drops itself (would delete its own cwd) — finish = `integrate`, then exit the worktree |
| `refresh` (self) | any ws | unchanged, + P1 guard |
| `repair`/`resolve`/`converge` | feature ws, self | unchanged |

Target selection: a mutating command defaults to the workspace you stand in; a
positional `NAME` is only honored from `default` (or, from a feature ws, if it
equals self).

## Preconditions

### P1 — trunk tip unambiguous

`default@` must have a single parent. Guard revset:

```
default@- & fork_point(default@-)
```

Non-empty iff single-parent (`fork_point(x)==x` for a single commit; returns the
parents' common ancestor ∉ `default@-` on a merge). **Applies to `refresh`,
`integrate`, and `start`** (all anchor their rebase on the trunk tip). Address as
`default@-` from a feature ws; bare `@-` is fine inside `integrate`'s
`-R <default-root>` invocation. `default@`-as-merge is pathological → belt-and-suspenders, surfaced with an
**explicit precondition check** (clear "default@ is a merge; coordinator line must
be linear" message), with the empty-revset guard as the mechanical backstop.

### P2 — feature refreshed-current

`integrate` refuses unless the feature is already detached onto the **current**
trunk tip (trunk tip is an ancestor of the feature). `refresh` establishes this,
so P2 is not a precondition to `refresh`. Payoff: `integrate`'s combined splice
has its detach portion as a guaranteed no-op → cannot hit a feature-vs-trunk
conflict. **`refresh` owns feature-vs-trunk conflicts; `integrate` assumes clean.**
Exact check intent: `fork_point(default@- | NAME@-) == default@-` (must-test).

## Rewritten commands

### `__workflow_start` — eliminate the `__tip` bookmark

Today (`scripts/workflow:271-290`) a 7-step dance uses a **fixed-name** transient
bookmark `__tip` with `create` (fail-if-exists); an interrupted run orphans it
and **permanently wedges all future workspace creation** (Bug 1). Replace with one
splice, no transient bookmark, coordinator `@` never moves:

```fish
set savepoint (__savepoint)
and begin
    jj new --no-edit -A 'default@- & fork_point(default@-)' -B default@ -m "start $name"
    and jj bookmark create $name -r default@-
    and jj workspace add "$ws_dir" -r $name
    or begin
        __rollback $savepoint
        rm -rf "$ws_dir"
        return 1
    end
end
and __provision_ws "$ws_dir"
```

- `jj new --no-edit -A <trunk-tip> -B default@` splices the empty base between
  trunk tip and `default@` (`trunk → E → default@`); `--no-edit` keeps coordinator
  `@` on `default@`. (`--no-edit`, `-A`, `-B` confirmed in jj 0.43.)
- After the splice, `default@`'s parent *is* the base, so `bookmark create $name
  -r default@-` names it.
- Identical topology to the `__tip` dance, in 3 commands; bakes in P1; reuses the
  same `-A <trunk> -B default@` idiom as integrate's advance.
- Interrupt can still orphan the *per-feature* `$name` bookmark (feature-scoped,
  surfaced by the dir-exists check + re-run) — far less severe than a global
  wedge. Consider a `start NAME` re-run that heals a stale `$name` + partial ws.

### `integrate` — combined detach + advance, run from the feature ws

Replace the advance's bare `@` (= `default@` only when run from `default`) and,
given P2, collapse detach + advance into one splice against `default`:

```
jj -R (jj workspace root --name default) \
   rebase -r 'bookmarks('$name') | default@..$name@-' \
          -A 'default@- & fork_point(default@-)' -B default@
```

- `-R <default-root>` loads the default workspace → `default@` is **mutable**
  here (see Immutability) and cwd no longer matters.
- `bookmarks(exact:"$name")` — the claim commit by exact bookmark match. Not bare
  `$name` (symbol ambiguity) and not `bookmarks("$name")` (jj string patterns
  default to `glob:`). The union covers the claimed-but-unworked case where
  `$name@` *is* the claim commit.
- `-A <trunk-tip> -B default@` splices claim+feature between trunk tip and
  `default@` (linear). Under P2 the detach is a no-op → only `default@` moves.
- **P1 guard is essential here** — a merge `default@` would splice onto both
  parents. Check P1 explicitly up front (clear message); the `-A` revset resolving
  empty is the mechanical backstop.
- The wip→done move + completion commit (`:862-864`) must **also** be re-addressed
  to run in `default`'s context (`jj -R <default-root> commit … $move_paths`,
  still path-scoped to ticket moves). **Audit *every* bare-`@`/cwd touchpoint in
  the default-line steps — `:850`, `:862`, `:864` are the known ones; the audit is
  the task.**
- Rejected alternative: `-r 'default@..$name@-' -B default@` re-anchors the feature
  itself — behaviorally identical in the normal topology but *masks* a broken
  detach instead of surfacing it. Prefer the form that surfaces breakage.

### `claim` from a feature ws — fold-into-self + description accretion

`claim T2` from a feature ws folds `T2` into *this* workspace's claim commit (no
cd). Each fold rewrites the description `claim a` → `claim a, b` — safe/cosmetic
(`integrate` reads slugs from the claim's diff paths `:835-839`, not the
description).

### `refresh` — add the P1 guard

`refresh` detaches onto `default@-`; add P1 so a merge `default@` fails cleanly.

## Guard split

Today's blanket gate (`:12-15`) becomes two-tier:

- **Creation + cross-feature ops** (`start`, `claim NAME`, `drop NAME`,
  `integrate NAME` naming a foreign ws) → must run from `default`.
- **Self-ops** (`integrate`, `claim`-fold, `refresh`, `repair`, `resolve`,
  `converge` targeting self) → self-or-`default`; refused from a *foreign* feature
  ws.

Enforcement generalizes `refresh:683-685`: *if cwd is a feature ws and target ≠
self → refuse.*

## Immutability interaction (why it's safe)

```
immutable_heads() = builtin_immutable_heads() | (default@ ~ @)
```

is evaluated relative to the invoking workspace's `@`. From a feature ws,
`default@ ~ @` = `default@` → the whole default line is immutable there; from
`default`'s context it's empty → mutable. So `integrate`'s `-R <default-root>` is
the *only* context where the default line is writable — get the `-R` wrong and jj
**refuses** rather than corrupting. Divergence safety is already handled by
`__snapshot_workspaces` (`:136`, called at `:889`), which must keep running before
the combined splice (it rewrites the feature's live WC via descendant-follow).
Concurrent-editor-on-`default` policy: **permissive** (snapshot + rebase, no gate).

## Bugs surfaced (in scope)

1. **`__tip` orphan-wedge** — fixed by the `__workflow_start` rewrite.
2. **`workflow start --help` starts a feature named `--help`** — no `-h`/`--help`
   handling and no dash-name rejection in arg parsing (produced the
   `mmqpqmrm "start --help"` litter). Fix: handle `-h`/`--help` (print usage) and
   reject any NAME beginning with `-` across subcommands.

## Phasing (single 0.4.0 release)

All one release — bug fixes fold in (delta to the redesign is trivial).
Implementation order:

1. Standalone fixes first (de-risk EnterWorktree): `__workflow_start` `__tip`
   rewrite + `--help`/dash-name guard.
2. Redesign: self-only invariant + guard split + P1 (explicit checks) + P2 +
   `integrate` combined splice + `claim` fold/accretion.
3. Bump `.claude-plugin/plugin.json` → 0.4.0; update README/SKILL.

## Out of scope

- **EnterWorktree *routing*** (agents not reaching for EnterWorktree on a
  ticket-claim) — a guidance/SKILL fix (`EnterWorktree(name: <ticket-slug>)`),
  independent of this toolkit change. Track separately.

## Must-test (real runs)

1. `integrate` from a feature ws with a **dirty feature WC** and a **live sibling
   workspace** — correct topology, no divergence, siblings left un-stale.
2. The combined splice `-A <trunk> -B default@` does not leave `default@` a
   redundant-parent merge in the linear case (may need `--simplify-parents`).
3. `__workflow_start` rewrite: `workspace add -r $name` lands the feature ws `@`
   sensibly; `__provision_ws` name matches the existing fn.
4. P2 check exact revset across: fresh claim (no work), multi-commit feature,
   feature behind trunk (must refuse), feature current (must pass).
5. Interrupt-safety: kill `start` mid-sequence → no global wedge; a `start NAME`
   re-run heals the per-feature orphan.
6. `-h`/`--help` on every subcommand prints usage; a `-`-leading NAME is refused.

## Decisions

- P1: **explicit precondition checks** with a clear message, backed by the
  empty-revset guard as a mechanical backstop.
- Single **0.4.0** release — `--help`/dash-name + `__tip` fixes fold in, not a
  separate 0.3.1.
