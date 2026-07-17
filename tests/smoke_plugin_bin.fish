#!/usr/bin/env fish
# Smoke: the plugin consumption model — NO toolkit scripts installed in the
# repo; everything driven through the toolkit's bin/ symlinks from a global
# location. Covers CWD-based workspace/lock resolution, the `todo_cmd` seam
# (project-provided ticket tool), and the full claim → integrate cycle.

set -l tk (path resolve (status dirname)/..)
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-bin: jj init failed"; exit 1; end
# Plugin model: no install.fish — the setup skill's one per-repo step is the alias.
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | (default@ ~ @)'
or begin; echo >&2 "smoke-bin: config set failed"; exit 1; end

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
jj commit -m "project setup" >/dev/null 2>&1; or begin; echo >&2 "smoke-bin: commit failed"; exit 1; end

# Claim a census-minted ticket through bin/workflow (symlink → scripts/workflow).
$tk/bin/workflow claim mech-x >/dev/null 2>&1
or begin; echo >&2 "smoke-bin: claim failed (rc=$status)"; exit 1; end
test -d $work/mech-x; or begin; echo >&2 "smoke-bin: workspace missing"; exit 1; end
grep -q 'ticket: mech-x' $work/mech-x/docs/tickets/wip/mech-x.md
or begin; echo >&2 "smoke-bin: minted ticket missing from claim"; exit 1; end
# Fresh claim hands over a NON-stale workspace (claim = start + adopt, with the
# adopt-squash staleness healed) whose claim commit carries the ticket move.
jj -R $work/mech-x st >/dev/null
or begin; echo >&2 "smoke-bin: fresh-claim workspace is stale"; exit 1; end
jj log --no-graph -r mech-x -T 'empty' --ignore-working-copy | string match -q false
or begin; echo >&2 "smoke-bin: mech-x claim commit is empty"; exit 1; end

# Work in the feature workspace, refresh via bin/ from inside it (CWD targeting).
cd $work/mech-x; or exit 1
echo done >mech-x.txt
jj commit -m "implement mech-x" >/dev/null 2>&1; or begin; echo >&2 "smoke-bin: feature commit failed"; exit 1; end
$tk/bin/workflow refresh >/dev/null 2>&1; or begin; echo >&2 "smoke-bin: refresh failed (rc=$status)"; exit 1; end

# Integrate from the coordinator; ticket must land in done/.
cd $coord; or exit 1
$tk/bin/workflow integrate mech-x >/dev/null 2>&1
or begin; echo >&2 "smoke-bin: integrate failed (rc=$status)"; exit 1; end
test -f $coord/mech-x.txt; or begin; echo >&2 "smoke-bin: work missing from trunk"; exit 1; end
test -f $coord/docs/tickets/done/mech-x.md
or begin; echo >&2 "smoke-bin: ticket not finished to done/"; exit 1; end

# Integrate keeps the workspace; plain abandon (claim bookmark gone) retires it.
test -d $work/mech-x; or begin; echo >&2 "smoke-bin: workspace dropped by integrate"; exit 1; end
$tk/bin/workflow abandon mech-x >/dev/null 2>&1
or begin; echo >&2 "smoke-bin: post-integrate abandon failed (rc=$status)"; exit 1; end
not test -e $work/mech-x; or begin; echo >&2 "smoke-bin: workspace dir survived abandon"; exit 1; end

# conflicts via bin/ resolves the repo from CWD too ("No conflicts found." on a
# clean tree; `list` intentionally propagates jj's nonzero no-conflict status).
$tk/bin/conflicts show 2>/dev/null | string match -q 'No conflicts found.'
or begin; echo >&2 "smoke-bin: conflicts show via bin failed"; exit 1; end

# Outside any jj repo, the toolkit refuses cleanly.
cd (mktemp -d); or exit 1
$tk/bin/workflow start nope >/dev/null 2>&1
and begin; echo >&2 "smoke-bin: ran outside a jj repo"; exit 1; end

echo "SMOKE-BIN PASS"
rm -rf $work
