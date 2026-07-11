---
name: jj-workflow
description: Use when working in a repo that uses the jj-workflow toolkit (scripts/jj, scripts/workflow, scripts/conflicts) — covers the claim→integrate feature lifecycle, the trunk-immutability guard, conflict recovery, and the alphabetized-list conflict auto-resolver.
---

# jj-workflow

This repo uses the jj-workflow toolkit. Read `README.md` for the full model. Key rules:

- Run jj only through a relative `scripts/jj` (never bare `jj`/`git`).
- Each feature = a `scripts/workflow claim NAME` (or `start NAME`) → work in `../NAME` → `scripts/workflow integrate NAME`.
- Before review, get current with trunk: run `scripts/workflow refresh` (no arg) from inside the feature workspace — detaches the stack onto the trunk tip; `integrate` re-joins the claim.
- Recover a shifted/divergent feature workspace with `scripts/workflow repair`.
- Resolve alphabetized-list conflicts with `scripts/conflicts auto`; inspect any conflict with `scripts/conflicts show`.
