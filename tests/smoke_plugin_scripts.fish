#!/usr/bin/env fish
# Smoke: the plugin consumption model — NO toolkit scripts installed in the
# repo; everything driven by absolute path out of the skill directory the way
# the skill tells an agent to. Covers CWD-based workspace/lock resolution, the
# `todo_cmd` seam (project-provided ticket tool), and the full claim → integrate
# cycle.

set -l tk (path resolve (status dirname)/..)
set -l skill_scripts $tk/skills/jj-workflow/scripts
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-scripts: jj init failed"; exit 1; end
# Plugin model: no install.fish — the setup skill's one per-repo step is the alias.
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | (default@ ~ @)'
or begin; echo >&2 "smoke-scripts: config set failed"; exit 1; end

# Project-provided ticket tool wired via jjworkflow.toml todo_cmd.
mkdir -p tools
printf '%s\n' '#!/usr/bin/env fish' \
    'switch "$argv[1]"' \
    '    case iscensus' \
    '        test "$argv[2]" = mech-x' \
    '    case mint' \
    '        echo "# ticket: $argv[2]"' \
    "    case '*'" \
    '        exit 1' \
    'end' >tools/mytodo
chmod +x tools/mytodo
printf 'todo_cmd = "tools/mytodo"\n' >jjworkflow.toml
jj commit -m "project setup" >/dev/null 2>&1; or begin; echo >&2 "smoke-scripts: commit failed"; exit 1; end

# Claim a census-minted ticket by absolute path.
$skill_scripts/workflow claim mech-x >/dev/null 2>&1
or begin; echo >&2 "smoke-scripts: claim failed (rc=$status)"; exit 1; end
test -d $work/mech-x; or begin; echo >&2 "smoke-scripts: workspace missing"; exit 1; end
grep -q 'ticket: mech-x' $work/mech-x/docs/tickets/wip/mech-x.md
or begin; echo >&2 "smoke-scripts: minted ticket missing from claim"; exit 1; end
# Fresh claim hands over a NON-stale workspace (claim = start + adopt, with the
# adopt-squash staleness healed) whose claim commit carries the ticket move.
jj -R $work/mech-x st >/dev/null
or begin; echo >&2 "smoke-scripts: fresh-claim workspace is stale"; exit 1; end
jj log --no-graph -r mech-x -T 'empty' --ignore-working-copy | string match -q false
or begin; echo >&2 "smoke-scripts: mech-x claim commit is empty"; exit 1; end

# Work in the feature workspace, refresh from inside it (CWD targeting).
cd $work/mech-x; or exit 1
echo done >mech-x.txt
jj commit -m "implement mech-x" >/dev/null 2>&1; or begin; echo >&2 "smoke-scripts: feature commit failed"; exit 1; end
$skill_scripts/workflow refresh >/dev/null 2>&1; or begin; echo >&2 "smoke-scripts: refresh failed (rc=$status)"; exit 1; end

# Integrate from the coordinator; ticket must land in done/.
cd $coord; or exit 1
$skill_scripts/workflow integrate mech-x >/dev/null 2>&1
or begin; echo >&2 "smoke-scripts: integrate failed (rc=$status)"; exit 1; end
test -f $coord/mech-x.txt; or begin; echo >&2 "smoke-scripts: work missing from trunk"; exit 1; end
test -f $coord/docs/tickets/done/mech-x.md
or begin; echo >&2 "smoke-scripts: ticket not finished to done/"; exit 1; end

# Integrate keeps the workspace; plain drop (claim bookmark gone) retires it.
test -d $work/mech-x; or begin; echo >&2 "smoke-scripts: workspace dropped by integrate"; exit 1; end
$skill_scripts/workflow drop mech-x >/dev/null 2>&1
or begin; echo >&2 "smoke-scripts: post-integrate drop failed (rc=$status)"; exit 1; end
not test -e $work/mech-x; or begin; echo >&2 "smoke-scripts: workspace dir survived drop"; exit 1; end

# conflicts resolves the repo from CWD too ("No conflicts found." on a
# clean tree; `list` intentionally propagates jj's nonzero no-conflict status).
$skill_scripts/conflicts show 2>/dev/null | string match -q 'No conflicts found.'
or begin; echo >&2 "smoke-scripts: conflicts show failed"; exit 1; end

# Outside any jj repo, the toolkit refuses cleanly.
cd (mktemp -d); or exit 1
$skill_scripts/workflow start nope >/dev/null 2>&1
and begin; echo >&2 "smoke-scripts: ran outside a jj repo"; exit 1; end

echo "SMOKE-SCRIPTS PASS"
rm -rf $work
