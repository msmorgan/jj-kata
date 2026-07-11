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

# The create hook works from anywhere in the repo, not just the coordinator.
set -l payload2 (jq -n --arg cwd $work/bg-test --arg n bg-two \
    '{hook_event_name: "WorktreeCreate", cwd: $cwd, worktree_name: $n,
      worktree_path: "ignored", base_ref: "main"}')
set -l out2 (printf '%s' $payload2 | fish $create)
or begin; echo >&2 "smoke-wt: create-from-feature-ws failed (rc=$status)"; exit 1; end
test "$out2" = "$work/bg-two"; or begin; echo >&2 "smoke-wt: got '$out2'"; exit 1; end

# Remove: maps to abandon — workspace forgotten, dir archived, exit 0.
echo scratch >$work/bg-test/scratch.txt
set -l rmpayload (jq -n --arg cwd $coord --arg p $work/bg-test \
    '{hook_event_name: "WorktreeRemove", cwd: $cwd, worktree_name: "bg-test", worktree_path: $p}')
printf '%s' $rmpayload | fish $remove
or begin; echo >&2 "smoke-wt: remove hook failed (rc=$status)"; exit 1; end
jj workspace list -T 'name ++ "\n"' | string match -q bg-test
and begin; echo >&2 "smoke-wt: workspace still registered after remove"; exit 1; end
test -d $work/.abandoned/bg-test
or begin; echo >&2 "smoke-wt: workspace not archived to .abandoned"; exit 1; end

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
