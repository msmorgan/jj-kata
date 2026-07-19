---
name: jj-workflow
description: Use when working in a repo that uses the jj-workflow toolkit (scripts/workflow, scripts/conflicts) — covers the claim→integrate feature lifecycle, the config-based trunk-immutability guard, conflict recovery, and the alphabetized-list conflict auto-resolver.
---

# jj-workflow

This repo uses the jj-workflow toolkit. Read `README.md` for the full model. Key rules:

- Run `jj` directly; immutability is enforced by a repo-config `immutable_heads()` alias, not a wrapper. Never run `git` (banned), and never pass `--config`/`--config-file`/`--ignore-immutable` (they bypass the guard).
- Each feature = a `scripts/workflow claim NAME` (or `start NAME`) → work in `../NAME` → finish it. **Two-tier:** the `default` coordinator drives creation and cross-feature ops (`start`, `claim NAME`, `drop NAME`, `integrate NAME` naming a sibling); a feature workspace acts on **itself only** and can finish itself in place — no `cd` back to `default`.
- Finish from inside the feature workspace (no NAME): `scripts/workflow integrate` integrates THIS workspace (it reaches into `default` internally). From `default`, `scripts/workflow integrate NAME` is unchanged. Naming a sibling from a feature workspace is refused.
- Fold extra tickets in place: from a feature workspace, `scripts/workflow claim TODO...` (no `--into`) folds each into THIS workspace's own claim (description accretes to `claim a, b`). `claim TODO... --into NAME` stays coordinator-only.
- Before review, get current with trunk: run `scripts/workflow refresh` (no arg) from inside the feature workspace — detaches the stack onto the trunk tip; `integrate` re-joins the claim. `refresh` owns feature-vs-trunk conflicts; `integrate` assumes clean.
- Two preconditions can refuse cleanly: **P1** — `refresh`/`integrate`/`start` refuse when `default@` is a merge (linearize the coordinator line first). **P2** — `integrate` refuses (exit 2) unless the feature is already refreshed onto the current trunk tip; run `scripts/workflow refresh` inside it first.
- On ANY conflict (exit `69`) or divergence, immediately run `scripts/workflow repair` (or `resolve`) from inside the feature workspace and reason through it step by step — **agent-initiated**, the toolkit never auto-runs repair. Both drop you onto the conflict and print the exact marker locations as `file:line` hits (e.g. `…/f.txt:12:<<<<<<< conflict 1 of 2`); Read those lines, remove every marker, re-run until exit 0.
- Resolve alphabetized-list conflicts with `scripts/conflicts auto`; inspect any conflict with `scripts/conflicts show`.
