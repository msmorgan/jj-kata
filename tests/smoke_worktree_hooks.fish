#!/usr/bin/env fish
# Smoke: the Claude Code WorktreeCreate/WorktreeRemove hook adapters. Feeds the
# harness's stdin payloads to the hook scripts and checks that EnterWorktree
# would get a real jj-workflow workspace and that removal maps to abandon.

set -l tk (path resolve (status dirname)/..)
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1
jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-wt: jj init failed"; exit 1; end
$tk/install.fish --copy $coord >/dev/null; or begin; echo >&2 "smoke-wt: install failed"; exit 1; end
mkdir -p docs/tickets/planned docs/tickets/wip docs/tickets/done
echo '# tick-x' >docs/tickets/planned/tick-x.md
jj commit -m "install toolkit" >/dev/null 2>&1; or begin; echo >&2 "smoke-wt: commit failed"; exit 1; end

set -l create $coord/scripts/hooks/worktree_create.fish
set -l remove $coord/scripts/hooks/worktree_remove.fish

# Create: hook must print the workspace dir (the harness trusts this path and
# ignores its own .claude/worktrees suggestion).
set -l payload (jq -n --arg cwd $coord --arg n bg-test \
    '{hook_event_name: "WorktreeCreate", cwd: $cwd, worktree_name: $n,
      worktree_path: ($cwd + "/.claude/worktrees/" + $n), base_ref: "main"}')
set -l out (printf '%s' $payload | fish $create)
or begin; echo >&2 "smoke-wt: create hook failed (rc=$status)"; exit 1; end
test "$out" = "$work/bg-test"
or begin; echo >&2 "smoke-wt: create returned '$out', want $work/bg-test"; exit 1; end
test -d $work/bg-test; or begin; echo >&2 "smoke-wt: workspace dir missing"; exit 1; end
jj workspace list -T 'name ++ "\n"' | string match -q bg-test
or begin; echo >&2 "smoke-wt: workspace not registered"; exit 1; end
# bg-test names no ticket → ad-hoc start, nothing claimed.
not test -e $coord/docs/tickets/wip/bg-test.md
or begin; echo >&2 "smoke-wt: ad-hoc create minted a ticket"; exit 1; end

# Create whose name matches a planned ticket: hook claims it (planned → wip).
set -l tickpayload (jq -n --arg cwd $coord --arg n tick-x \
    '{hook_event_name: "WorktreeCreate", cwd: $cwd, worktree_name: $n,
      worktree_path: ($cwd + "/.claude/worktrees/" + $n), base_ref: "main"}')
set -l tickout (printf '%s' $tickpayload | fish $create)
or begin; echo >&2 "smoke-wt: ticket create hook failed (rc=$status)"; exit 1; end
test "$tickout" = "$work/tick-x"
or begin; echo >&2 "smoke-wt: ticket create returned '$tickout'"; exit 1; end
test -f $coord/docs/tickets/wip/tick-x.md
or begin; echo >&2 "smoke-wt: matching ticket was not claimed to wip"; exit 1; end

# The create hook works from anywhere in the repo, not just the coordinator.
set -l payload2 (jq -n --arg cwd $work/bg-test --arg n bg-two \
    '{hook_event_name: "WorktreeCreate", cwd: $cwd, worktree_name: $n,
      worktree_path: "ignored", base_ref: "main"}')
set -l out2 (printf '%s' $payload2 | fish $create)
or begin; echo >&2 "smoke-wt: create-from-feature-ws failed (rc=$status)"; exit 1; end
test "$out2" = "$work/bg-two"; or begin; echo >&2 "smoke-wt: got '$out2'"; exit 1; end

# Remove maps to PLAIN abandon: a workspace holding un-integrated work is
# refused — still registered, dir intact — while the hook itself exits 0.
echo scratch >$work/bg-test/scratch.txt
set -l rmpayload (jq -n --arg cwd $coord --arg p $work/bg-test \
    '{hook_event_name: "WorktreeRemove", cwd: $cwd, worktree_name: "bg-test", worktree_path: $p}')
printf '%s' $rmpayload | fish $remove 2>/dev/null
or begin; echo >&2 "smoke-wt: remove hook exited nonzero"; exit 1; end
jj workspace list -T 'name ++ "\n"' | string match -q bg-test
or begin; echo >&2 "smoke-wt: workspace with work was dropped by remove"; exit 1; end
test -d $work/bg-test
or begin; echo >&2 "smoke-wt: workspace dir with work deleted by remove"; exit 1; end

# An untouched ad-hoc workspace sweeps clean (harness unchanged-worktree cleanup).
set -l rmpayload2 (jq -n --arg cwd $coord --arg p $work/bg-two \
    '{hook_event_name: "WorktreeRemove", cwd: $cwd, worktree_name: "bg-two", worktree_path: $p}')
printf '%s' $rmpayload2 | fish $remove
or begin; echo >&2 "smoke-wt: remove hook (untouched ws) exited nonzero"; exit 1; end
jj workspace list -T 'name ++ "\n"' | string match -q bg-two
and begin; echo >&2 "smoke-wt: untouched workspace still registered after remove"; exit 1; end
not test -e $work/bg-two
or begin; echo >&2 "smoke-wt: untouched workspace dir not deleted"; exit 1; end

# --force is the explicit path for discarding real work.
scripts/workflow abandon --force bg-test >/dev/null 2>&1
or begin; echo >&2 "smoke-wt: abandon --force failed (rc=$status)"; exit 1; end
not test -e $work/bg-test
or begin; echo >&2 "smoke-wt: bg-test dir survived abandon --force"; exit 1; end

# Remove for a path that is not a workspace of this repo: silent no-op, exit 0.
set -l noop (jq -n --arg cwd $coord \
    '{hook_event_name: "WorktreeRemove", cwd: $cwd, worktree_name: "zzz", worktree_path: "/tmp/zzz"}')
printf '%s' $noop | fish $remove
or begin; echo >&2 "smoke-wt: no-op remove exited nonzero"; exit 1; end

# Create outside any jj repo must fail loudly (EnterWorktree should error).
set -l outside (mktemp -d)
set -l badpayload (jq -n --arg cwd $outside \
    '{hook_event_name: "WorktreeCreate", cwd: $cwd, worktree_name: "nope", worktree_path: "x", base_ref: "main"}')
printf '%s' $badpayload | fish $create >/dev/null 2>&1
and begin; echo >&2 "smoke-wt: create succeeded outside a jj repo"; exit 1; end

echo "SMOKE-WT PASS"
rm -rf $work $outside
