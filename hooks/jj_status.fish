#!/usr/bin/env fish
# hooks/jj_status.fish — status line for a jj-workflow repo.
#
# Claude Code and Codex register this on SessionStart (orientation) and on
# PostToolUse for their write, edit, and shell tools. Google Antigravity runs it
# after write/update/command tools too, then calls it again at PreInvocation to
# inject the pending line using that harness's output contract.
#
# PostToolUse is intentional. It snapshots every agent-authored change as soon
# as the tool finishes, shrinking the window in which another workspace rewrite
# can leave divergent successors. The hook still emits context only when the
# rendered status line changed, so a no-op shell command stays silent.
#
# Claude/Codex payloads use hook_event_name, session_id, cwd, and tool_name.
# Antigravity payloads use toolCall, conversationId, workspacePaths, and camelCase
# arguments. Never log the raw payload: tool inputs and responses may be large or
# sensitive.
#
# Exit is always 0. A status probe must never stop a turn or session start.

set -l payload (cat | string collect)
test -n "$payload"; or exit 0

set -l is_antigravity (printf '%s' $payload | jq -r \
    'if (.conversationId and (.toolCall or has("invocationNum"))) then "true" else "false" end' 2>/dev/null)
set -l event (printf '%s' $payload | jq -r '
    .hook_event_name //
    (if .toolCall then "PostToolUse"
     elif has("invocationNum") then "PreInvocation"
     else "" end)' 2>/dev/null)

switch "$event"
    case SessionStart PostToolUse PreInvocation
    case '*'
        exit 0
end

# Resolve the workspace from the harness payload. File tools in Antigravity do
# not carry Cwd, so their target path is the most precise fallback; the first
# mounted workspace is the final fallback.
set -l cwd (printf '%s' $payload | jq -r '.cwd // .toolCall.args.Cwd // ""' 2>/dev/null)
set -l mounted (printf '%s' $payload | jq -r '.workspacePaths[0] // ""' 2>/dev/null)
set -l target (printf '%s' $payload | jq -r '.toolCall.args.TargetFile // ""' 2>/dev/null)
if test -z "$cwd"
    if test -n "$target"
        string match -q -- '/*' "$target"; or set target "$mounted/$target"
        set cwd (path dirname "$target")
    else
        set cwd "$mounted"
    end
end
if test -n "$cwd" -a -d "$cwd"
    cd "$cwd"; or begin
        test "$is_antigravity" = true; and echo '{}'
        exit 0
    end
end

# A plugin install enables this hook globally. Avoid spawning jj outside a jj
# repo, and return Antigravity's required empty object when there is no work.
set -l d $PWD
while not test -d "$d/.jj"
    set -l parent (path dirname $d)
    if test "$parent" = "$d"
        test "$is_antigravity" = true; and echo '{}'
        exit 0
    end
    set d $parent
end
set -l root (command jj workspace root --ignore-working-copy 2>/dev/null)
if test -z "$root"
    test "$is_antigravity" = true; and echo '{}'
    exit 0
end

set -l sid (printf '%s' $payload | jq -r '.session_id // .conversationId // "nosession"' 2>/dev/null)
set -l cache "$root/.jj/workflow-status.$sid"
set -l pending "$root/.jj/workflow-status-pending.$sid"
set -l at_start 0
test "$event" = SessionStart; and set at_start 1

# Antigravity cannot inject context from PostToolUse. That event snapshots and
# leaves a pending line; PreInvocation delivers it as an ephemeral message. The
# first invocation has no SessionStart equivalent, so it reports directly.
if test "$event" = PreInvocation
    if test -r "$pending"
        set -l line (cat "$pending" 2>/dev/null)
        rm -f "$pending" 2>/dev/null
        jq -n --arg line "$line" '{injectSteps: [{ephemeralMessage: $line}]}'
        exit 0
    end
    set -l invocation (printf '%s' $payload | jq -r '.invocationNum // -1' 2>/dev/null)
    if test "$invocation" != 0
        echo '{}'
        exit 0
    end
    set at_start 1
end

set -l self (path dirname (path resolve (status filename)))
set -l out (fish "$self/../skills/jj-workflow/scripts/workflow" status --porcelain 2>/dev/null)
if test -z "$out"
    test "$is_antigravity" = true; and echo '{}'
    exit 0
end
set -l parts (string split -m1 \t -- $out)
if test (count $parts) -ne 2
    test "$is_antigravity" = true; and echo '{}'
    exit 0
end
set -l key $parts[1]
set -l line $parts[2]

# The key is the complete rendered line. The probe always runs (and therefore
# snapshots) for a registered tool, while context is suppressed only when the
# agent would see the exact same status again.
if test $at_start -eq 0; and test -r "$cache"
    set -l prev (cat "$cache" 2>/dev/null)
    if test "$prev" = "$key"
        test "$is_antigravity" = true; and echo '{}'
        exit 0
    end
end
printf '%s\n' "$key" >"$cache" 2>/dev/null

# One file per session accumulates. A week is longer than a resumable session is
# useful; session orientation is the natural place to sweep old cache files.
if test $at_start -eq 1
    find "$root/.jj" -maxdepth 1 -name 'workflow-status.*' -mtime +7 -delete 2>/dev/null
    find "$root/.jj" -maxdepth 1 -name 'workflow-status-pending.*' -mtime +7 -delete 2>/dev/null
end

if test "$event" = SessionStart
    # SessionStart consumes bare stdout in both Claude Code and Codex.
    printf '%s\n' "$line"
else if test "$is_antigravity" = true
    if test "$event" = PreInvocation
        jq -n --arg line "$line" '{injectSteps: [{ephemeralMessage: $line}]}'
    else
        printf '%s\n' "$line" >"$pending" 2>/dev/null
        echo '{}'
    end
else
    jq -n --arg line "$line" '{hookSpecificOutput: {
        hookEventName: "PostToolUse",
        additionalContext: $line
    }}'
end
exit 0
