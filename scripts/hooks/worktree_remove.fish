#!/usr/bin/env fish
# WorktreeRemove hook: retire the jj-workflow workspace that the paired
# WorktreeCreate hook made for EnterWorktree. Maps to plain `workflow abandon`:
# an integrated (or untouched ad-hoc) workspace is dropped and its directory
# deleted; one still holding un-integrated work is REFUSED — workspace and
# commits stay put until it's integrated or `abandon --force`d by hand.
#
# The harness fires this on session-exit "remove", unchanged-subagent cleanup,
# and its periodic sweep; the exit status is advisory (cleanup proceeds), so
# anything that isn't clearly ours to remove is a silent no-op.
#
# stdin: {"cwd": …, "worktree_name": …, "worktree_path": …}

set -l payload (cat | string collect)
set -l wt_path (printf '%s' $payload | jq -r '.worktree_path // ""')
set -l cwd (printf '%s' $payload | jq -r '.cwd // ""')
test -n "$wt_path"; or exit 0
test -n "$cwd"; and cd "$cwd"

set -l droot (jj workspace root --name default --ignore-working-copy 2>/dev/null)
test -n "$droot"; or exit 0
cd "$droot"; or exit 0

# Only touch it if it is actually a workspace of THIS repo.
set -l name (path basename $wt_path)
jj workspace list --ignore-working-copy -T 'name ++ "\n"' 2>/dev/null | string match -q -- "$name"
or exit 0

set -l self (path dirname (path resolve (status filename)))
fish "$self/../workflow" abandon "$name" >&2
exit 0
