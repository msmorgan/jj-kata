#!/usr/bin/env fish
# Smoke: where feature workspaces land.
#   1. `workspace_dir` in jjworkflow.toml relocates them — exercising the hardest
#      case, an in-repo gitignored base, and checking it never leaks into the
#      coordinator's snapshots.
#   2. With no config, an UNWRITABLE parent directory (the shape of a sandboxed
#      agent host) switches the default from `..` to the in-repo
#      `.codex/workspaces`, so workspaces stay somewhere writable. The writable-
#      parent default (`../NAME`) is covered by the other smokes.

set -l tk (path resolve (status dirname)/..)
set -l work (mktemp -d)
set -l coord $work/myproj
set -l coord_sandboxed $work/sandboxed-proj

# --- Set both projects up while $work is still writable. --------------------
mkdir -p $coord $coord_sandboxed; or exit 1

cd $coord; or exit 1
jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: jj init failed"; exit 1; end
$tk/install.fish --copy $coord >/dev/null; or begin; echo >&2 "smoke-wsdir: install failed"; exit 1; end
printf 'workspace_dir = ".claude/worktrees"\n' >jjworkflow.toml
printf '.claude/worktrees/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: commit failed"; exit 1; end

cd $coord_sandboxed; or exit 1
jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: sandboxed jj init failed"; exit 1; end
$tk/install.fish --copy $coord_sandboxed >/dev/null
or begin; echo >&2 "smoke-wsdir: sandboxed install failed"; exit 1; end
printf '.codex/workspaces/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: sandboxed setup commit failed"; exit 1; end

# Everything below runs with the projects' shared parent read-only, so a
# workspace that tried to land at `../NAME` could not be created at all.
chmod a-w $work; or begin; echo >&2 "smoke-wsdir: could not make the parent read-only"; exit 1; end
function _restore --on-event fish_exit --inherit-variable work
    chmod u+w $work 2>/dev/null
end
if test -w $work
    # Running as root (or on a filesystem that ignores the mode) — the premise
    # of the sandbox half cannot hold.
    echo >&2 "smoke-wsdir: SKIP — the parent stayed writable after chmod a-w"
    chmod u+w $work; rm -rf $work
    exit 0
end

# --- 1. An explicit workspace_dir wins, sandboxed host or not. --------------
cd $coord; or exit 1
scripts/workflow start feat-z >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: configured start failed"; exit 1; end
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
scripts/workflow drop feat-z >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: post-integrate drop failed (rc=$status)"; exit 1; end
not test -e $coord/.claude/worktrees/feat-z
or begin; echo >&2 "smoke-wsdir: workspace dir not deleted after drop"; exit 1; end

# Drop deletes under the configured base too.
scripts/workflow start feat-q >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: second start failed"; exit 1; end
scripts/workflow drop feat-q >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: drop failed"; exit 1; end
not test -e $coord/.claude/worktrees/feat-q
or begin; echo >&2 "smoke-wsdir: workspace dir not deleted after drop"; exit 1; end

# --- 2. No config + unwritable parent -> the in-repo default. ---------------
cd $coord_sandboxed; or exit 1
scripts/workflow start feat-c >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: sandboxed default start failed"; exit 1; end
test -d $coord_sandboxed/.codex/workspaces/feat-c
or begin; echo >&2 "smoke-wsdir: sandboxed workspace escaped repo root"; exit 1; end
not test -e $work/feat-c
or begin; echo >&2 "smoke-wsdir: sandboxed workspace used sibling default"; exit 1; end
jj status >/dev/null 2>&1
set leaked (jj file list 2>/dev/null | string match -- '.codex/*')
if set -q leaked[1]
    echo >&2 "smoke-wsdir: sandboxed base leaked into coordinator snapshot: $leaked"; exit 1
end
scripts/workflow drop feat-c >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: sandboxed default drop failed"; exit 1; end
not test -e $coord_sandboxed/.codex/workspaces/feat-c
or begin; echo >&2 "smoke-wsdir: sandboxed workspace dir not deleted"; exit 1; end

echo "SMOKE-WSDIR PASS"
chmod u+w $work
rm -rf $work
