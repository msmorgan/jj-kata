# Lifecycle recovery and exceptional operations

Read the branch matching the command or result in front of you. Preserve Kata's
exit status and output; do not pipe lifecycle commands.

## Exit contract

- `0`: the transition completed.
- `2`: Kata refused before the transition. Correct the reported input,
  configuration, ownership, or topology problem before retrying.
- `69`: Kata preserved or created an expected recovery state. Review the
  reported state and use the matching recovery branch below.
- `75`: the repository Kata lock timed out. Confirm the competing lifecycle
  operation has ended before retrying.
- `130`: the command was interrupted. Inspect the reported workspace state
  before deciding whether to retry.

Unexpected jj failures exit 1.

## Refresh every live feature

From `default`, refresh all eligible feature workspaces in one preflighted
operation:

```bash
/PLUGIN/scripts/kata refresh --all
```

Kata validates every target before refreshing any target. It completes when it
exits 0 and reports the changed and already-current workspace counts.

## Concurrent workspace edits

Kata snapshots live workspaces before graph rewrites and rechecks each banked
working-copy commit immediately before the first rebase that could affect its
branch. If another edit arrives during that interval, Kata preserves the new
snapshot and exits 69. Review the newly snapshotted work; retry the same Kata
command only when that workspace is ready for the rewrite.

## Conflicts

If refresh or integration reports conflicts, stop and use jj-sensei's harmony
skill in the named workspace. Resume the lifecycle only after Harmony's repair
criteria are satisfied. Operation-log surgery is not part of Kata recovery.

## Archive a closed attempt

Run archive inside a feature workspace whose work has been closed to an empty,
undescribed `@`:

```bash
/PLUGIN/scripts/kata archive
```

It preserves the closed stack under `archive-WORKSPACE` and backs that attempt
out of the active workspace. For a shared claim, Kata copies the claim beneath
the archive and leaves `@` above the original claim so the workspace retains
ownership. For a feature-local claim or bare workspace, it starts a fresh empty
`@` at `fork_point(@ | default@)`; the archived stack retains any local claim.

Archive completes when it exits 0 and reports the archive bookmark. It refuses
an empty stack, non-claim-rooted shared topology, or an existing archive
bookmark without changing that state.

## Drop unfinished work

Plain drop protects unintegrated work by refusing it. From `default`, choose an
exception only when the user explicitly wants that outcome:

```bash
/PLUGIN/scripts/kata drop NAME --return-items
/PLUGIN/scripts/kata drop NAME --force
```

`--return-items` runs the configured return transition, preserves its reported
paths, refuses newer default-side edits to governed item paths, and retains the
source workspace until the return commit succeeds. `--force` discards the
unintegrated workspace stack. There is no safe bulk-drop selector because fresh
and integrated empty workspaces are not visibly distinguishable.
