---
name: jj-workflow
description: Use when working in a repo that uses the jj-workflow toolkit (scripts/workflow, scripts/conflicts) — covers the claim→integrate feature lifecycle, the config-based trunk-immutability guard, conflict recovery, and the alphabetized-list conflict auto-resolver.
---

# jj-workflow

This repo uses the jj-workflow toolkit. Read `README.md` for the full model. Key rules:

- Run `jj` directly; immutability is enforced by a repo-config `immutable_heads()` alias, not a wrapper. Never run `git` (banned), and never pass `--config`/`--config-file`/`--ignore-immutable` (they bypass the guard).
- Each feature = a `scripts/workflow claim NAME` (or `start NAME`) → work in `../NAME` → `scripts/workflow integrate NAME`.
- Before review, get current with trunk: run `scripts/workflow refresh` (no arg) from inside the feature workspace — detaches the stack onto the trunk tip; `integrate` re-joins the claim.
- On ANY conflict (exit `69`) or divergence, immediately run `scripts/workflow repair` (or `resolve`) from inside the feature workspace and reason through it step by step — **agent-initiated**, the toolkit never auto-runs repair. Both drop you onto the conflict and print the exact marker locations as `file:line` hits (e.g. `…/f.txt:12:<<<<<<< conflict 1 of 2`); Read those lines, remove every marker, re-run until exit 0.
- Resolve alphabetized-list conflicts with `scripts/conflicts auto`; inspect any conflict with `scripts/conflicts show`.
