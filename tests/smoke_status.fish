#!/usr/bin/env fish
# Smoke: `workflow status` and the cross-harness PostToolUse hook adapter.
# Covers the line's content in each state that changes what an agent may do
# (coordinator vs feature workspace, empty vs dirty @, un-integrated depth,
# conflicts), and the hook's two jobs: snapshot every write/update/shell tool
# immediately, and stay quiet only when the rendered line is unchanged.

set -l tk (path resolve (status dirname)/..)
set -g wf $tk/skills/jj-workflow/scripts/workflow
set -g cf $tk/skills/jj-workflow/scripts/conflicts
set -l work (mktemp -d)
set -l coord $work/myproj
set -l ws $coord/.workspaces
mkdir -p $coord; or exit 1
cd $coord; or exit 1
jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-status: jj init failed"; exit 1; end
jj config set --repo 'revset-aliases."all_if_any(rev)"' 'descendants(ancestors(rev))' >/dev/null
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | ((working_copies() ~ @) & all_if_any(default@ ~ @))' >/dev/null
echo A >f.txt
jj commit -m "base" >/dev/null 2>&1
or begin; echo >&2 "smoke-status: commit failed"; exit 1; end

set -l hook $tk/hooks/jj_status.fish

# --- The line itself ---------------------------------------------------------

# Coordinator, nothing in @: names the workspace, says (empty), and omits the
# un-integrated count (structurally always 0 on default — a meaningless zero).
set -l line (fish $wf status)
or begin; echo >&2 "smoke-status: status failed on default (rc=$status)"; exit 1; end
string match -q 'jj: default | @ *(empty)*' -- $line
or begin; echo >&2 "smoke-status: want 'jj: default … (empty)', got: $line"; exit 1; end
string match -q '*unintegrated*' -- $line
and begin; echo >&2 "smoke-status: default should not report unintegrated: $line"; exit 1; end

# Dirty, undescribed @: file counts by kind alongside line counts. The hook is
# what forces the snapshot in real use; calling status does it here too, which is
# the point — nothing has reached the repo until a jj command runs.
printf 'l1\nl2\nl3\n' >new.txt
set line (fish $wf status)
string match -q '*(no desc) +3/-0 (+1/~0/-0)*' -- $line
or begin; echo >&2 "smoke-status: want '(no desc) +3/-0 (+1/~0/-0)', got: $line"; exit 1; end

# Described @ shows the description instead of (no desc).
jj describe -m "add new.txt" >/dev/null 2>&1
set line (fish $wf status)
string match -q '*"add new.txt"*' -- $line
or begin; echo >&2 "smoke-status: description not shown: $line"; exit 1; end

# --- Rendered-line key -------------------------------------------------------
# The KEY is what the hook diffs. Edit volume is visible in the line, so another
# edit in the SAME change must move the key and re-arm context injection.
set -l key1 (string split -m1 \t -- (fish $wf status --porcelain))[1]
printf 'l4\nl5\n' >>new.txt
set -l porc2 (string split -m1 \t -- (fish $wf status --porcelain))
test "$porc2[1]" != "$key1"
or begin; echo >&2 "smoke-status: key ignored changed edit volume: '$key1' -> '$porc2[1]'"; exit 1; end
string match -q '*+5/-0*' -- $porc2[2]
or begin; echo >&2 "smoke-status: porcelain line did not track the new edits: $porc2[2]"; exit 1; end
# A content replacement with identical rendered stats stays suppressed, even
# though the status probe still snapshots it.
printf 'a\nb\nc\nd\ne\n' >new.txt
set -l key_same (string split -m1 \t -- (fish $wf status --porcelain))[1]
test "$key_same" = "$porc2[1]"
or begin; echo >&2 "smoke-status: key differs while rendered line is identical"; exit 1; end
# A new change id also moves the key.
jj commit -m "close it" >/dev/null 2>&1
set -l key3 (string split -m1 \t -- (fish $wf status --porcelain))[1]
test "$key3" != "$key_same"
or begin; echo >&2 "smoke-status: key did not move across a commit"; exit 1; end

# --- Feature workspace -------------------------------------------------------

fish $wf start feat >/dev/null 2>&1
or begin; echo >&2 "smoke-status: start failed"; exit 1; end
cd $ws/feat; or begin; echo >&2 "smoke-status: no feat workspace dir"; exit 1; end

# status runs from a feature workspace (it only reads, so it is exempt from the
# coordinator-only gate) and reports THAT workspace, not default.
set line (fish $wf status)
or begin; echo >&2 "smoke-status: status failed in feature ws (rc=$status)"; exit 1; end
string match -q 'jj: feat |*' -- $line
or begin; echo >&2 "smoke-status: want 'jj: feat', got: $line"; exit 1; end
string match -q '*0 unintegrated*' -- $line
or begin; echo >&2 "smoke-status: fresh feature ws should be 0 unintegrated: $line"; exit 1; end

# Work that trunk does not have yet is what decides whether integrate does
# anything, so it must be counted.
echo B >f.txt
jj commit -m "feat work" >/dev/null 2>&1
set line (fish $wf status)
string match -q '*1 unintegrated*' -- $line
or begin; echo >&2 "smoke-status: want '1 unintegrated', got: $line"; exit 1; end

# --- Conflicts ---------------------------------------------------------------
# Trunk moves under the feature, then refresh rebases onto it: same line, two
# edits. refresh stops nonzero on the conflict; status must SAY so.
cd $coord; or exit 1
echo C >f.txt
jj commit -m "trunk moves" >/dev/null 2>&1
cd $ws/feat; or exit 1
fish $wf refresh >/dev/null 2>&1
set line (fish $wf status)
string match -q '*⚠*conflicted*' -- $line
or begin; echo >&2 "smoke-status: conflict not reported: $line"; exit 1; end

# --- The hook ----------------------------------------------------------------

cd $coord; or exit 1
# A file write has not reached jj yet. PostToolUse must snapshot it immediately
# and inject the newly dirty line using the Claude/Codex output contract.
set -l ops_before (jj op log --no-graph -T '"x\n"' --ignore-working-copy | count)
echo untracked >scratch.txt
set -l write_payload (jq -n --arg cwd $coord '{hook_event_name:"PostToolUse",cwd:$cwd,
    session_id:"s1",tool_name:"Write",tool_input:{},tool_response:{}}')
set -l out (printf '%s' $write_payload | fish $hook)
or begin; echo >&2 "smoke-status: hook exited nonzero after Write"; exit 1; end
set -l ctx (printf '%s' $out | jq -r '.hookSpecificOutput.additionalContext // ""')
string match -q 'jj: default |*(no desc) +1/-0*' -- $ctx
or begin; echo >&2 "smoke-status: hook additionalContext wrong: '$ctx'"; exit 1; end
test (jj op log --no-graph -T '"x\n"' --ignore-working-copy | count) -gt $ops_before
or begin; echo >&2 "smoke-status: Write hook did not snapshot the working copy"; exit 1; end

# Same rendered state, another call: silence. The probe still ran; only duplicate
# context is suppressed.
set -l again (printf '%s' $write_payload | fish $hook)
test -z "$again"
or begin; echo >&2 "smoke-status: hook repeated an unchanged state: $again"; exit 1; end

# Edit volume changes the rendered line and therefore re-arms the hook.
echo second >>scratch.txt
set -l edit_payload (jq -n --arg cwd $coord '{hook_event_name:"PostToolUse",cwd:$cwd,
    session_id:"s1",tool_name:"Edit",tool_input:{},tool_response:{}}')
set out (printf '%s' $edit_payload | fish $hook)
set ctx (printf '%s' $out | jq -r '.hookSpecificOutput.additionalContext // ""')
string match -q '*+2/-0*' -- $ctx
or begin; echo >&2 "smoke-status: Edit did not report changed volume: '$ctx'"; exit 1; end

# Codex reports apply_patch canonically even though the matcher aliases it to
# Write/Edit; unified exec is canonical Bash. Both must use PostToolUse context.
echo third >>scratch.txt
set -l patch_payload (jq -n --arg cwd $coord '{hook_event_name:"PostToolUse",cwd:$cwd,
    session_id:"s1",tool_name:"apply_patch",tool_input:{command:"*** patch"},tool_response:{}}')
set out (printf '%s' $patch_payload | fish $hook)
set ctx (printf '%s' $out | jq -r '.hookSpecificOutput.additionalContext // ""')
string match -q '*+3/-0*' -- $ctx
or begin; echo >&2 "smoke-status: Codex apply_patch shape failed: '$ctx'"; exit 1; end

echo fourth >>scratch.txt
set -l bash_payload (jq -n --arg cwd $coord '{hook_event_name:"PostToolUse",cwd:$cwd,
    session_id:"s1",tool_name:"Bash",tool_input:{command:"printf"},tool_response:{}}')
set out (printf '%s' $bash_payload | fish $hook)
set ctx (printf '%s' $out | jq -r '.hookSpecificOutput.additionalContext // ""')
string match -q '*+4/-0*' -- $ctx
or begin; echo >&2 "smoke-status: Bash shape failed: '$ctx'"; exit 1; end

# Sessions do not swallow each other's first line.
set -l other (jq -n --arg cwd $coord '{hook_event_name:"PostToolUse",cwd:$cwd,
    session_id:"s2",tool_name:"Edit"}' | fish $hook)
test -n "$other"
or begin; echo >&2 "smoke-status: second session got no first line"; exit 1; end

# The cache lives in .jj/, which jj never snapshots — it must not show up as a
# working-copy change.
jj status | string match -q '*workflow-status*'
and begin; echo >&2 "smoke-status: status cache leaked into the working copy"; exit 1; end

# A structural move re-arms it too.
jj describe -m "now described" >/dev/null 2>&1
set -l after (printf '%s' $bash_payload | fish $hook)
test -n "$after"
or begin; echo >&2 "smoke-status: hook stayed silent across a structural change"; exit 1; end

# Antigravity's PostToolUse contract accepts only `{}`. The hook snapshots there,
# stores changed context, and delivers it at the next PreInvocation as an
# ephemeral message. Exercise every Antigravity mutation tool family.
for tool in write_to_file replace_file_content multi_replace_file_content
    echo $tool >>scratch.txt
    set -l ag_post (jq -n --arg cwd $coord --arg tool $tool --arg target "$coord/scratch.txt" \
        '{conversationId:"g1",workspacePaths:[$cwd],toolCall:{name:$tool,args:{TargetFile:$target}}}')
    set -l ag_ack (printf '%s' $ag_post | fish $hook)
    printf '%s' $ag_ack | jq -e 'type == "object" and length == 0' >/dev/null
    or begin; echo >&2 "smoke-status: Antigravity $tool did not return {}: $ag_ack"; exit 1; end
    set -l ag_pre (jq -n --arg cwd $coord '{conversationId:"g1",workspacePaths:[$cwd],
        invocationNum:1,initialNumSteps:1}')
    set -l ag_ctx (printf '%s' $ag_pre | fish $hook | jq -r '.injectSteps[0].ephemeralMessage // ""')
    string match -q 'jj: default |*' -- $ag_ctx
    or begin; echo >&2 "smoke-status: Antigravity $tool context missing: '$ag_ctx'"; exit 1; end
end

echo run_command >>scratch.txt
set -l ag_run (jq -n --arg cwd $coord '{conversationId:"g1",workspacePaths:[$cwd],
    toolCall:{name:"run_command",args:{Cwd:$cwd,CommandLine:"printf"}}}')
set -l ag_ack (printf '%s' $ag_run | fish $hook)
printf '%s' $ag_ack | jq -e 'type == "object" and length == 0' >/dev/null
or begin; echo >&2 "smoke-status: Antigravity run_command did not return {}: $ag_ack"; exit 1; end
set -l ag_pre (jq -n --arg cwd $coord '{conversationId:"g1",workspacePaths:[$cwd],
    invocationNum:2,initialNumSteps:2}')
set -l ag_ctx (printf '%s' $ag_pre | fish $hook | jq -r '.injectSteps[0].ephemeralMessage // ""')
string match -q 'jj: default |*' -- $ag_ctx
or begin; echo >&2 "smoke-status: Antigravity run_command context missing: '$ag_ctx'"; exit 1; end

# Antigravity has no SessionStart event; invocation zero supplies orientation.
set -l ag_boot (jq -n --arg cwd $coord '{conversationId:"gboot",workspacePaths:[$cwd],
    invocationNum:0,initialNumSteps:0}' | fish $hook)
set -l ag_boot_ctx (printf '%s' $ag_boot | jq -r '.injectSteps[0].ephemeralMessage // ""')
string match -q 'jj: default |*' -- $ag_boot_ctx
or begin; echo >&2 "smoke-status: Antigravity initial context missing: '$ag_boot_ctx'"; exit 1; end

# --- SessionStart ------------------------------------------------------------
# The other end of the same problem: a session that has just started, resumed, or
# been compacted knows nothing about where it is.

# It reports a BARE line, not the PostToolUse JSON envelope — on SessionStart
# it is exit-0 stdout that reaches the model, so JSON would show it the wrapper.
set -l ss (jq -n --arg cwd $coord '{hook_event_name:"SessionStart",cwd:$cwd,
    session_id:"boot",source:"startup"}' | fish $hook)
or begin; echo >&2 "smoke-status: SessionStart hook exited nonzero"; exit 1; end
string match -q 'jj: default |*' -- $ss
or begin; echo >&2 "smoke-status: SessionStart line wrong: '$ss'"; exit 1; end
string match -q '*hookSpecificOutput*' -- $ss
and begin; echo >&2 "smoke-status: SessionStart emitted JSON, not a bare line"; exit 1; end

# It must IGNORE the suppression cache. resume/clear/compact/fork reuse the
# session id, and those are exactly the events that discarded the context holding
# the previous line — staying quiet there would be quiet at the worst moment.
set -l resumed (jq -n --arg cwd $coord '{hook_event_name:"SessionStart",cwd:$cwd,
    session_id:"boot",source:"resume"}' | fish $hook)
test -n "$resumed"
or begin; echo >&2 "smoke-status: SessionStart was suppressed by its own cache"; exit 1; end
# …while a tool call in the same session, same state, still stays quiet.
set -l quiet (jq -n --arg cwd $coord '{hook_event_name:"PostToolUse",cwd:$cwd,
    session_id:"boot",tool_name:"Edit"}' | fish $hook)
test -z "$quiet"
or begin; echo >&2 "smoke-status: SessionStart broke tool suppression: $quiet"; exit 1; end

# Session start sweeps caches left by sessions that are long gone.
touch -d '30 days ago' $coord/.jj/workflow-status.ancient
touch -d '30 days ago' $coord/.jj/workflow-status-pending.ancient
jq -n --arg cwd $coord '{hook_event_name:"SessionStart",cwd:$cwd,
    session_id:"boot",source:"startup"}' | fish $hook >/dev/null
not test -e $coord/.jj/workflow-status.ancient
or begin; echo >&2 "smoke-status: stale status cache was not swept"; exit 1; end
not test -e $coord/.jj/workflow-status-pending.ancient
or begin; echo >&2 "smoke-status: stale pending status was not swept"; exit 1; end
test -e $coord/.jj/workflow-status.boot
or begin; echo >&2 "smoke-status: sweep took the live session's cache too"; exit 1; end

# Registered globally, the hook fires in non-jj projects too: silent, exit 0.
set -l outside (mktemp -d)
set -l nonjj (jq -n --arg cwd $outside '{hook_event_name:"PostToolUse",cwd:$cwd,
    session_id:"s1",tool_name:"Edit"}' | fish $hook)
or begin; echo >&2 "smoke-status: hook exited nonzero outside a jj repo"; exit 1; end
test -z "$nonjj"; or begin; echo >&2 "smoke-status: hook spoke outside a jj repo: $nonjj"; exit 1; end
set -l nonjj_boot (jq -n --arg cwd $outside '{hook_event_name:"SessionStart",cwd:$cwd,
    session_id:"s1",source:"startup"}' | fish $hook)
or begin; echo >&2 "smoke-status: SessionStart exited nonzero outside a jj repo"; exit 1; end
test -z "$nonjj_boot"
or begin; echo >&2 "smoke-status: SessionStart spoke outside a jj repo: $nonjj_boot"; exit 1; end

# Antigravity requires a valid empty JSON object even when the hook is outside a
# jj repo and has no context to inject.
set -l nonjj_ag (jq -n --arg cwd $outside '{conversationId:"g-out",workspacePaths:[$cwd],
    toolCall:{name:"run_command",args:{Cwd:$cwd,CommandLine:"true"}}}' | fish $hook)
printf '%s' $nonjj_ag | jq -e 'type == "object" and length == 0' >/dev/null
or begin; echo >&2 "smoke-status: Antigravity non-jj response invalid: $nonjj_ag"; exit 1; end

# The per-tool PostToolUse shape still works, for anyone who registers it there.
set -l ptu (jq -n --arg cwd $coord '{hook_event_name:"PostToolUse",cwd:$cwd,
    session_id:"s3",tool_name:"Write",tool_input:{}}' | fish $hook)
string match -q '*jj: default*' -- $ptu
or begin; echo >&2 "smoke-status: PostToolUse payload shape not handled: $ptu"; exit 1; end

echo "SMOKE-STATUS PASS"
rm -rf $work $outside
