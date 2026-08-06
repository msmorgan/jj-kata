#!/usr/bin/env fish
# Smoke: where feature workspaces land.
#   1. The default is the in-repo `.workspaces/`, and the toolkit makes it
#      invisible to jj ITSELF by dropping a `.gitignore` holding `*` inside it —
#      no per-repo setup step, nothing to forget. The coordinator must never
#      snapshot a child workspace.
#   2. `workspace_dir` in jjworkflow.toml overrides it, including back out to the
#      sibling layout, and an in-repo override gets the same self-ignore.

set -l tk (path resolve (status dirname)/..)
set -g wf $tk/skills/jj-workflow/scripts/workflow
set -g cf $tk/skills/jj-workflow/scripts/conflicts
set -l work (mktemp -d)
set -l coord $work/myproj
set -l ws $coord/.workspaces
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: jj init failed"; exit 1; end
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | (default@ ~ @)' >/dev/null
jj commit -m "base" >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: commit failed"; exit 1; end

# --- 1. The default base, self-ignored. -------------------------------------
# No jjworkflow.toml, no .gitignore, no setup step: just start a workspace.
$wf start feat-z >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: default start failed"; exit 1; end
test -d $coord/.workspaces/feat-z
or begin; echo >&2 "smoke-wsdir: workspace not under the default .workspaces/ base"; exit 1; end
not test -e $work/feat-z
or begin; echo >&2 "smoke-wsdir: workspace landed outside the repo"; exit 1; end
test (cat $coord/.workspaces/.gitignore) = '*'
or begin; echo >&2 "smoke-wsdir: base was not self-ignored"; exit 1; end

# The base — including its own .gitignore — must be invisible to the coordinator.
jj status >/dev/null 2>&1
set -l leaked (jj file list 2>/dev/null | string match -- '.workspaces/*')
if set -q leaked[1]
    echo >&2 "smoke-wsdir: base leaked into coordinator snapshot: $leaked"; exit 1
end
jj status 2>/dev/null | string match -q '*.workspaces*'
and begin; echo >&2 "smoke-wsdir: base showed up in coordinator status"; exit 1; end

# A workspace nested under an ignored base still tracks its OWN files normally —
# the base's `*` must not leak downward past the workspace root.
cd $coord/.workspaces/feat-z; or exit 1
echo note >note.txt
jj status | string match -q '*note.txt*'
or begin; echo >&2 "smoke-wsdir: feature workspace did not snapshot its own file"; exit 1; end
jj commit -m "feat: note" >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: feature commit failed"; exit 1; end
cd $coord; or exit 1

$wf integrate feat-z >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: integrate failed (rc=$status)"; exit 1; end
test -f $coord/note.txt; or begin; echo >&2 "smoke-wsdir: integrated work missing from trunk"; exit 1; end
test -d $coord/.workspaces/feat-z
or begin; echo >&2 "smoke-wsdir: workspace dir not kept after integrate"; exit 1; end
$wf drop feat-z >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: post-integrate drop failed (rc=$status)"; exit 1; end
not test -e $coord/.workspaces/feat-z
or begin; echo >&2 "smoke-wsdir: workspace dir not deleted after drop"; exit 1; end
# Dropping the last workspace leaves the base (and its ignore) in place.
test -f $coord/.workspaces/.gitignore
or begin; echo >&2 "smoke-wsdir: base ignore removed by drop"; exit 1; end

# --- 2. An explicit in-repo workspace_dir gets the same treatment. ----------
set -l coord_cfg $work/cfgproj
mkdir -p $coord_cfg; or exit 1
cd $coord_cfg; or exit 1
jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: cfg jj init failed"; exit 1; end
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | (default@ ~ @)' >/dev/null
printf 'workspace_dir = ".claude/worktrees"\n' >jjworkflow.toml
jj commit -m "base" >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: cfg commit failed"; exit 1; end

$wf start feat-c >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: configured start failed"; exit 1; end
test -d $coord_cfg/.claude/worktrees/feat-c
or begin; echo >&2 "smoke-wsdir: workspace not under the configured base"; exit 1; end
not test -e $coord_cfg/.workspaces
or begin; echo >&2 "smoke-wsdir: config was ignored in favour of the default base"; exit 1; end
test (cat $coord_cfg/.claude/worktrees/.gitignore) = '*'
or begin; echo >&2 "smoke-wsdir: configured in-repo base was not self-ignored"; exit 1; end
jj status >/dev/null 2>&1
set leaked (jj file list 2>/dev/null | string match -- '.claude/*')
if set -q leaked[1]
    echo >&2 "smoke-wsdir: configured base leaked into coordinator snapshot: $leaked"; exit 1
end
$wf drop feat-c >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: configured drop failed"; exit 1; end

# --- 3. `workspace_dir = ".."` still puts workspaces outside the repo. ------
# The sibling layout is a supported override, not dead code; nothing in the repo
# should be created for it.
set -l coord_sib $work/sibproj
mkdir -p $coord_sib; or exit 1
cd $coord_sib; or exit 1
jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: sibling jj init failed"; exit 1; end
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | (default@ ~ @)' >/dev/null
printf 'workspace_dir = ".."\n' >jjworkflow.toml
jj commit -m "base" >/dev/null 2>&1; or begin; echo >&2 "smoke-wsdir: sibling commit failed"; exit 1; end

$wf start feat-s >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: sibling start failed"; exit 1; end
test -d $work/feat-s
or begin; echo >&2 "smoke-wsdir: sibling workspace not created next to the repo"; exit 1; end
not test -e $coord_sib/.workspaces
or begin; echo >&2 "smoke-wsdir: sibling layout still created an in-repo base"; exit 1; end
not test -e $work/.gitignore
or begin; echo >&2 "smoke-wsdir: self-ignore was written outside the repo"; exit 1; end
$wf drop feat-s >/dev/null 2>&1
or begin; echo >&2 "smoke-wsdir: sibling drop failed"; exit 1; end

echo "SMOKE-WSDIR PASS"
rm -rf $work
