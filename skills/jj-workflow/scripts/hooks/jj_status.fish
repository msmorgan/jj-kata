#!/usr/bin/env fish
# scripts/hooks/jj_status.fish — status line for a jj-workflow repo.
# Registered on SessionStart (orientation) and PostToolBatch (keeping current).
#
# Gives an agent the thing a human gets for free from a shell prompt: where the
# working copy stands, read at the start and re-read at every point the agent
# stops to think.
#
# WHY PostToolBatch and not PostToolUse or UserPromptSubmit.
# A status line injected at UserPromptSubmit is freshest at the top of a turn —
# the moment it is needed least, since nothing has happened yet — and oldest
# thirty tool calls in, where the mistakes actually happen. PostToolBatch fires
# once after every tool call in a batch resolves, immediately BEFORE the next
# model request, so the line is never stale at the moment it is read.
# PostToolUse would work too, but it fires per-tool and may run CONCURRENTLY for
# parallel tool calls: five parallel edits would race five hooks for one jj
# working-copy lock and write five snapshot operations into a shared op log.
# One batch, one snapshot, one op.
#
# AND SessionStart, for the opposite reason: a fresh, resumed, cleared, forked, or
# just-compacted session is the one moment an agent knows NOTHING about where it
# is, so that is where the line is worth the most. It reports unconditionally
# there — see the suppression note below for why it must ignore its own cache.
#
# stdin: {"hook_event_name": "PostToolBatch", "cwd": …, "session_id": …,
#         "tool_calls": [{"tool_name": …, "tool_input": …, "tool_response": …}]}
#         or {"hook_event_name": "SessionStart", "cwd": …, "session_id": …,
#         "source": "startup"|"resume"|"clear"|"compact"|"fork"} — no tool_calls.
#         The per-tool PostToolUse shape (top-level .tool_name) is accepted too,
#         so the hook still works if registered on that event instead.
# stdout: PostToolBatch — JSON carrying the line as additionalContext.
#         SessionStart — the bare line; there, exit 0 stdout is what reaches the
#         model, so emitting JSON would show the model its own envelope.
#         Either way: nothing at all when there is nothing to say.
# exit:   always 0. These events can halt a turn or a session start; a status
#         probe must never be the reason either one stops.
#
# NOTE: tool_response for every tool in the batch arrives on stdin, so a batch
# containing a large Read puts that whole file here. The hook only ever looks at
# tool_name — do not add logging of the raw payload.

set -l payload (cat | string collect)
test -n "$payload"; or exit 0

set -l event (printf '%s' $payload | jq -r '.hook_event_name // ""' 2>/dev/null)
set -l at_start 0
test "$event" = SessionStart; and set at_start 1

# Tools that cannot possibly have changed the repo. A batch made only of these
# is skipped WITHOUT invoking jj at all — no lock, no working-copy scan. Most
# batches during exploration are exactly this, so the common case costs nothing.
# The list is a strict allowlist: anything unrecognised (including every Bash
# call, which could run anything) counts as mutating. Being wrong in that
# direction costs one no-op snapshot; being wrong the other way means silently
# reporting a state that has already moved.
set -l readonly_tools Read Grep Glob LS NotebookRead WebFetch WebSearch \
    TodoWrite Task TaskCreate TaskUpdate TaskGet TaskList TaskOutput \
    BashOutput ToolSearch Skill AskUserQuestion

# SessionStart carries no tool_calls and has nothing to skip — it always reports.
if test $at_start -eq 0
    set -l tools (printf '%s' $payload | jq -r '
        if .tool_calls then .tool_calls[].tool_name
        elif .tool_name then .tool_name
        else empty end' 2>/dev/null)
    set -q tools[1]; or exit 0

    set -l mutating 0
    for t in $tools
        if not contains -- "$t" $readonly_tools
            set mutating 1
            break
        end
    end
    test $mutating -eq 1; or exit 0
end

# A plugin install enables this hook in EVERY project — act only inside a jj
# repo. Walk up for a .jj dir first (same test jj_guard makes): a filesystem walk
# costs nothing, where spawning jj in every non-jj project would cost a process
# per batch forever.
set -l cwd (printf '%s' $payload | jq -r '.cwd // ""' 2>/dev/null)
if test -n "$cwd" -a -d "$cwd"
    cd "$cwd"; or exit 0
end
set -l d $PWD
while not test -d "$d/.jj"
    set -l parent (path dirname $d)
    test "$parent" = "$d"; and exit 0
    set d $parent
end
set -l root (command jj workspace root --ignore-working-copy 2>/dev/null)
test -n "$root"; or exit 0

set -l self (path dirname (path resolve (status filename)))
set -l out (fish "$self/../workflow" status --porcelain 2>/dev/null)
test -n "$out"; or exit 0
set -l parts (string split -m1 \t -- $out)
test (count $parts) -eq 2; or exit 0
set -l key $parts[1]
set -l line $parts[2]

# Say it once. The KEY changes only on a STRUCTURAL move — different workspace,
# different change id, described/undescribed, un-integrated count, conflicts,
# stale, bookmark on @ — never on edit volume alone. So twenty edits into one
# change produce one line, and silence afterwards means "still there", which is
# the whole reason this is affordable to run after every batch.
#
# The cache lives in the workspace's own .jj/ (never snapshotted, so it cannot
# leak into a commit) and is keyed by session, so two agents sharing a workspace
# each get their own first line rather than swallowing each other's.
#
# SessionStart deliberately IGNORES the cache. On `startup` the session id is new
# and there is nothing to ignore, but `resume`, `clear`, `compact`, and `fork`
# reuse it — and those are exactly the events that threw away the context holding
# the last line. Suppressing there would stay quiet precisely when the agent has
# just been left with no idea where it is.
set -l sid (printf '%s' $payload | jq -r '.session_id // "nosession"' 2>/dev/null)
set -l cache "$root/.jj/workflow-status.$sid"
if test $at_start -eq 0; and test -r "$cache"
    set -l prev (cat "$cache" 2>/dev/null)
    test "$prev" = "$key"; and exit 0
end
printf '%s\n' "$key" >"$cache" 2>/dev/null

# One file per session accumulates, so sweep old ones while we are here — session
# start is the natural GC point, and a week is long past any session that could
# still be resumed against them.
test $at_start -eq 1
and find "$root/.jj" -maxdepth 1 -name 'workflow-status.*' -mtime +7 -delete 2>/dev/null

if test $at_start -eq 1
    printf '%s\n' "$line"
else
    jq -n --arg line "$line" '{hookSpecificOutput: {
        hookEventName: "PostToolBatch",
        additionalContext: $line
    }}'
end
exit 0
