# Item-driver protocol

Configure a driver in the default workspace's `jjkata.toml`:

```toml
[items]
driver = "scripts/items"
```

A string is split like a command line. An array preserves arguments exactly.
Relative executable paths containing `/` resolve from the default workspace.

## Lifecycle invocation

Kata runs:

```text
DRIVER ACTION [REQUESTED_ITEM ...]
```

The current directory is the workspace whose tree the action may inspect or
change. stdin is one JSON object:

```json
{
  "version": 1,
  "action": "owned",
  "workspace": "feature-name",
  "requested": [],
  "context": {
    "base_revision": "fork_point(default@ | feature-name@)",
    "revision": "feature-name@",
    "visibility": "feature"
  }
}
```

`base_revision` and `revision` are jj revsets meaningful in the current
repository. They may be null for `probe` and `claim`.

Exit zero and print one JSON object:

```json
{
  "items": ["opaque-item-id"],
  "paths": ["queue/item.task", "doing/item.task"]
}
```

`items` contains opaque IDs. For mutating actions, `paths` contains every
repository-relative path changed, including both sides of a move. For `owned`,
it contains every path governed by those items in either contextual tree; Kata
uses that set to refuse `--return-items` before mutation when unrelated work is
present. Paths must remain inside the workspace. Kata treats them as literal jj
filesets. Write diagnostics to stderr and use a nonzero exit status on failure.

## Actions

- `probe`: report the subset of requested items that are uniquely claimable;
  do not mutate. WorktreeCreate uses this to choose claim versus ad-hoc start.
- `claim`: move requested markers into the active state and report their IDs
  and changed paths.
- `owned`: derive the feature's owned IDs and governed paths from
  `base_revision` and `revision`; do not mutate or use an external metadata
  ledger.
- `complete`: move requested owned markers into the completed state and report
  changed paths.
- `return`: restore requested markers to the state derived from
  `base_revision`, preserving workspace edits, and report changed paths.

The graph is the source of truth. A driver must give the same `owned` answer
for an equivalent reconstructed jj tree, regardless of whether Kata created
the changes.

## Inspection invocation

When `[kanban] command = "scripts/todo"` is configured,
`jj-kata kanban COMMAND [ITEM]` delegates directly as:

```text
KANBAN_COMMAND COMMAND [ITEM]
```

No lifecycle JSON is sent. Use ordinary stdout, stderr, and exit status for
`board`, `ready`, `blocked`, `graph`, `needs`, and `check`.
