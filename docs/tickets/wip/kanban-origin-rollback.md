# Preserve ownership after a claimed item returns to its origin

The built-in Kanban driver's endpoint-only ownership inference forgets a
feature-visible claim when `planned/item.md` moves through WIP and returns to
that exact original path. Integration must still recognize the item and refuse
completion while it is outside WIP.

Acceptance criteria:

- Derive ownership from visible feature history, not only its endpoint trees.
- Refuse integration with exit 69 when an owned item is back in triage.
- Guide the agent toward `drop --return-items`.
- Preserve the existing done/deleted refusal behavior and bare-start behavior.
