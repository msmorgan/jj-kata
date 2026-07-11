#!/usr/bin/env fish
# Smoke: `workspace_dir` in jjworkflow.toml relocates feature workspaces.
# Exercises the hardest case — an in-repo, gitignored base — and checks it
# never leaks into the coordinator's snapshots.

set -l tk (path resolve (status dirname)/..)
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: jj init failed"; exit 1; end
$tk/install.fish --copy $coord >/dev/null; or begin; echo >&2 "smoke-wsdir: install failed"; exit 1; end
printf 'workspace_dir = ".claude/worktrees"\n' >jjworkflow.toml
printf '.claude/worktrees/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: commit failed"; exit 1; end

scripts/workflow start feat-z >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: start failed"; exit 1; end
test -d $coord/.claude/worktrees/feat-z
or begin; echo >&2 "smoke-wsdir: workspace not under configured base"; exit 1; end
if test -e $work/feat-z
    echo >&2 "smoke-wsdir: workspace leaked to the default sibling location"; exit 1
end

cd $coord/.claude/worktrees/feat-z; or exit 1
echo note >note.txt
jj commit -m "feat: note" >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: feature commit failed"; exit 1; end
cd $coord; or exit 1

# The in-repo base must stay invisible to the coordinator's snapshots.
jj status >/dev/null 2>&1
set -l leaked (jj file list 2>/dev/null | string match -- '.claude/*')
if set -q leaked[1]
    echo >&2 "smoke-wsdir: base leaked into coordinator snapshot: $leaked"; exit 1
end

scripts/workflow integrate feat-z >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: integrate failed (rc=$status)"; exit 1; end
test -f $coord/note.txt; or begin; echo >&2 "smoke-wsdir: integrated work missing from trunk"; exit 1; end
test -d $coord/.claude/worktrees/feat-z
or begin; echo >&2 "smoke-wsdir: workspace dir not kept after integrate"; exit 1; end
scripts/workflow abandon feat-z >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: post-integrate abandon failed (rc=$status)"; exit 1; end
not test -e $coord/.claude/worktrees/feat-z
or begin; echo >&2 "smoke-wsdir: workspace dir not deleted after abandon"; exit 1; end

# Abandon deletes under the configured base too.
scripts/workflow start feat-q >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: second start failed"; exit 1; end
scripts/workflow abandon feat-q >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: abandon failed"; exit 1; end
not test -e $coord/.claude/worktrees/feat-q
or begin; echo >&2 "smoke-wsdir: workspace dir not deleted after abandon"; exit 1; end

echo "SMOKE-WSDIR PASS"
rm -rf $work
