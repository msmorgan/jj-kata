#!/usr/bin/env fish
# Smoke: `workflow status` and the PostToolBatch hook adapter that reports it.
# Covers the line's content in each state that changes what an agent may do
# (coordinator vs feature workspace, empty vs dirty @, un-integrated depth,
# conflicts), and the hook's two jobs: skip batches that cannot have changed
# anything, and stay quiet until something STRUCTURAL moves.

set -l tk (path resolve (status dirname)/..)
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1
jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-status: jj init failed"; exit 1; end
$tk/install.fish --copy $coord >/dev/null; or begin; echo >&2 "smoke-status: install failed"; exit 1; end
echo A >f.txt
jj commit -m "install toolkit" >/dev/null 2>&1
or begin; echo >&2 "smoke-status: commit failed"; exit 1; end

set -l wf $coord/scripts/workflow
set -l hook $coord/scripts/hooks/jj_status.fish

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

# --- Structural key vs edit volume -------------------------------------------
# The KEY is what the hook diffs. More edits to the SAME change must not move it,
# or the suppression it exists for would never suppress anything.
set -l key1 (string split -m1 \t -- (fish $wf status --porcelain))[1]
printf 'l4\nl5\n' >>new.txt
set -l porc2 (string split -m1 \t -- (fish $wf status --porcelain))
test "$porc2[1]" = "$key1"
or begin; echo >&2 "smoke-status: key moved on edit volume alone: '$key1' -> '$porc2[1]'"; exit 1; end
# …but the LINE it carries did update, so a report that does fire is accurate.
string match -q '*+5/-0*' -- $porc2[2]
or begin; echo >&2 "smoke-status: porcelain line did not track the new edits: $porc2[2]"; exit 1; end
# A real structural move (new change id) does move the key.
jj commit -m "close it" >/dev/null 2>&1
set -l key3 (string split -m1 \t -- (fish $wf status --porcelain))[1]
test "$key3" != "$key1"
or begin; echo >&2 "smoke-status: key did not move across a commit"; exit 1; end

# --- Feature workspace -------------------------------------------------------

fish $wf start feat >/dev/null 2>&1
or begin; echo >&2 "smoke-status: start failed"; exit 1; end
cd $work/feat; or begin; echo >&2 "smoke-status: no feat workspace dir"; exit 1; end

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
cd $work/feat; or exit 1
fish $wf refresh >/dev/null 2>&1
set line (fish $wf status)
string match -q '*⚠*conflicted*' -- $line
or begin; echo >&2 "smoke-status: conflict not reported: $line"; exit 1; end

# --- The hook ----------------------------------------------------------------

cd $coord; or exit 1
set -l mk_payload "jq -n --arg cwd $coord"

# A batch of nothing but read-only tools is skipped outright — no jj, no lock, no
# snapshot operation in the shared op log.
set -l ops_before (jj op log --no-graph -T '"x\n"' --ignore-working-copy | count)
echo untracked >scratch.txt
set -l ro (jq -n --arg cwd $coord '{hook_event_name:"PostToolBatch",cwd:$cwd,
    session_id:"s1",tool_calls:[{tool_name:"Read"},{tool_name:"Grep"}]}' | fish $hook)
or begin; echo >&2 "smoke-status: hook exited nonzero on read-only batch"; exit 1; end
test -z "$ro"; or begin; echo >&2 "smoke-status: read-only batch produced output: $ro"; exit 1; end
test (jj op log --no-graph -T '"x\n"' --ignore-working-copy | count) -eq $ops_before
or begin; echo >&2 "smoke-status: read-only batch still snapshotted the working copy"; exit 1; end

# A batch containing anything else reports, as additionalContext the harness
# delivers to the model.
set -l edit_payload (jq -n --arg cwd $coord '{hook_event_name:"PostToolBatch",cwd:$cwd,
    session_id:"s1",tool_calls:[{tool_name:"Edit",tool_input:{},tool_response:"ok"}]}')
set -l out (printf '%s' $edit_payload | fish $hook)
or begin; echo >&2 "smoke-status: hook exited nonzero on mutating batch"; exit 1; end
set -l ctx (printf '%s' $out | jq -r '.hookSpecificOutput.additionalContext // ""')
string match -q 'jj: default |*' -- $ctx
or begin; echo >&2 "smoke-status: hook additionalContext wrong: '$ctx'"; exit 1; end

# Same structural state, another batch: silence. This is what makes a per-batch
# hook affordable — an unchanged state costs nothing to report.
set -l again (printf '%s' $edit_payload | fish $hook)
test -z "$again"
or begin; echo >&2 "smoke-status: hook repeated an unchanged state: $again"; exit 1; end

# Sessions do not swallow each other's first line.
set -l other (jq -n --arg cwd $coord '{hook_event_name:"PostToolBatch",cwd:$cwd,
    session_id:"s2",tool_calls:[{tool_name:"Edit"}]}' | fish $hook)
test -n "$other"
or begin; echo >&2 "smoke-status: second session got no first line"; exit 1; end

# The cache lives in .jj/, which jj never snapshots — it must not show up as a
# working-copy change.
jj status | string match -q '*workflow-status*'
and begin; echo >&2 "smoke-status: status cache leaked into the working copy"; exit 1; end

# A structural move re-arms it.
jj describe -m "now described" >/dev/null 2>&1
set -l after (printf '%s' $edit_payload | fish $hook)
test -n "$after"
or begin; echo >&2 "smoke-status: hook stayed silent across a structural change"; exit 1; end

# Registered globally, the hook fires in non-jj projects too: silent, exit 0.
set -l outside (mktemp -d)
set -l nonjj (jq -n --arg cwd $outside '{hook_event_name:"PostToolBatch",cwd:$cwd,
    session_id:"s1",tool_calls:[{tool_name:"Edit"}]}' | fish $hook)
or begin; echo >&2 "smoke-status: hook exited nonzero outside a jj repo"; exit 1; end
test -z "$nonjj"; or begin; echo >&2 "smoke-status: hook spoke outside a jj repo: $nonjj"; exit 1; end

# The per-tool PostToolUse shape still works, for anyone who registers it there.
set -l ptu (jq -n --arg cwd $coord '{hook_event_name:"PostToolUse",cwd:$cwd,
    session_id:"s3",tool_name:"Write",tool_input:{}}' | fish $hook)
string match -q '*jj: default*' -- $ptu
or begin; echo >&2 "smoke-status: PostToolUse payload shape not handled: $ptu"; exit 1; end

echo "SMOKE-STATUS PASS"
rm -rf $work $outside
