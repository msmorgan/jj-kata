#!/usr/bin/env fish
# WorktreeCreate hook: back Claude Code's EnterWorktree with a jj-workflow
# feature workspace instead of a git worktree — a background session that
# isolates before editing gets the toolkit's native model (claim commit +
# workspace under the configured base), and `workflow integrate`/`abandon`
# close the loop.
#
# Register PER-REPO (the setup skill offers this), never in a plugin's global
# hooks.json: a configured WorktreeCreate hook REPLACES the native git-worktree
# logic for every repo it is active in, so enabling it globally would hijack
# EnterWorktree in plain-git projects.
#
# stdin:  {"cwd": …, "worktree_name": …, "worktree_path": …, "base_ref": …}
# stdout: the created workspace directory (the harness trusts this path and
#         ignores its own worktree_path suggestion). Nonzero exit fails the
#         EnterWorktree call.

set -l payload (cat | string collect)
set -l name (printf '%s' $payload | jq -r '.worktree_name // ""')
set -l cwd (printf '%s' $payload | jq -r '.cwd // ""')
if test -z "$name"
    echo >&2 "worktree_create: no worktree_name in hook payload."
    exit 1
end
test -n "$cwd"; and cd "$cwd"

# `workflow start` must run from the default (coordinator) workspace; the
# session may currently sit elsewhere in the repo.
set -l droot (jj workspace root --name default --ignore-working-copy 2>/dev/null)
if test -z "$droot"
    echo >&2 "worktree_create: not inside a jj repo with a default workspace."
    exit 1
end
cd "$droot"; or exit 1

# base_ref is ignored deliberately: feature workspaces always start from the
# trunk tip (default@-) — that is the jj-workflow model. --or-start claims the
# matching ticket/census row when the worktree name names one, so a background
# session pointed at a ticket picks it up properly; anything else is an
# ad-hoc start.
set -l self (path dirname (path resolve (status filename)))
fish "$self/../workflow" claim --or-start "$name" >&2
or exit 1

# Report where it landed — ask jj rather than recomputing the config.
jj workspace root --name "$name" --ignore-working-copy
