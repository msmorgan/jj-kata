#!/usr/bin/env fish
# Smoke: `workflow handoffs` — the read-only scan backing the handoff skill.
# A HANDOFF.md in a workspace checkout means work was paused there. The scan
# must find one in ANY workspace from ANY workspace, report grep-style status
# (0 = found, 1 = none), and — the case that matters most — still find a doc
# that was accidentally COMMITTED, because the whole point of the resume-side
# check is to catch exactly that mistake. Fish has no `set -e`; guard every
# must-pass step with `; or ...`.

set -l tk (path resolve (status dirname)/..)
set -g wf $tk/skills/jj-workflow/scripts/workflow
set -g cf $tk/skills/jj-workflow/scripts/conflicts
set -l work (mktemp -d)
set -l coord $work/myproj
set -l ws $coord/.workspaces
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init >/dev/null 2>&1; or begin
    echo >&2 "smoke-handoff: jj git init failed"
    exit 1
end
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | (default@ ~ @)' >/dev/null
jj commit -m "base" >/dev/null 2>&1; or begin
    echo >&2 "smoke-handoff: commit failed"
    exit 1
end

set -l fails 0
function _fail --argument-names msg
    echo >&2 "smoke-handoff: $msg"
    set -g fails (math $fails + 1)
end

# --- A clean repo has nothing paused: exit 1, no output. -------------------
set -l out ($wf handoffs 2>/dev/null)
set -l rc $status
test $rc -eq 1; or _fail "clean repo did not report 'none' (rc=$rc)"
test -z "$out"; or _fail "clean repo printed hits: $out"

for name in feat-a feat-b feat-c
    $wf start $name >/dev/null 2>&1; or begin
        echo >&2 "smoke-handoff: start $name failed"
        exit 1
    end
end

# Workspaces with no handoff are still nothing to resume.
$wf handoffs >/dev/null 2>&1
test $status -eq 1; or _fail "workspaces without handoffs were reported as hits"

# --- One handoff, seen from the coordinator. ------------------------------
printf '# HANDOFF\n\nresume feat-a\n' >$ws/feat-a/HANDOFF.md
set out ($wf handoffs 2>/dev/null)
test $status -eq 0; or _fail "a present handoff did not exit 0"
test (count $out) -eq 1; or _fail "expected exactly 1 hit, got "(count $out)
echo $out[1] | string match -q "feat-a	$ws/feat-a/HANDOFF.md"
or _fail "hit line is not NAME<TAB>PATH: $out[1]"
echo "ok: finds a handoff in a sibling workspace, NAME<TAB>PATH, exit 0"

# --- Found from a feature workspace too (read-only ⇒ allowed anywhere). ----
# feat-b has no handoff of its own; it must still see feat-a's, and must not be
# refused by the coordinator-only gate.
pushd $ws/feat-b
set out ($wf handoffs 2>/dev/null)
set rc $status
popd
test $rc -eq 0; or _fail "handoffs was refused from a feature workspace (rc=$rc)"
test (count $out) -eq 1; or _fail "feature-ws scan saw "(count $out)" hits, expected 1"
echo "ok: runs from a feature workspace, not just default"

# --- Several at once, and default itself counts as a workspace. -----------
printf '# HANDOFF\n\nresume feat-c\n' >$ws/feat-c/HANDOFF.md
printf '# HANDOFF\n\npaused on the coordinator\n' >$coord/HANDOFF.md
set out ($wf handoffs 2>/dev/null)
test $status -eq 0; or _fail "multi-hit scan did not exit 0"
test (count $out) -eq 3; or _fail "expected 3 hits, got "(count $out)": $out"
string join \n $out | string match -q '*default	'$coord'/HANDOFF.md*'
or _fail "the default workspace's own handoff was not reported"
echo "ok: reports every workspace holding one, including default"

# --- The load-bearing case: a COMMITTED handoff is still found. -----------
# The doc is supposed to sit uncommitted in @, but presence is a plain `test -f`
# precisely so an accidental commit does not hide it — the resume side then
# catches the mistake by noticing it is absent from `jj st`.
rm $coord/HANDOFF.md $ws/feat-c/HANDOFF.md
pushd $ws/feat-a
command jj workspace update-stale >/dev/null 2>&1
jj commit -m "oops: committed the handoff doc" >/dev/null 2>&1; or begin
    echo >&2 "smoke-handoff: committing the handoff failed"
    popd
    exit 1
end
# Now on disk but NOT part of @'s changes — the exact state the skill flags.
jj st 2>/dev/null | string match -q '*HANDOFF.md*'
and _fail "committed handoff still shows as a working-copy change"
popd
set out ($wf handoffs 2>/dev/null)
test $status -eq 0; or _fail "a committed handoff was not found (it must be)"
test (count $out) -eq 1; or _fail "committed-handoff scan saw "(count $out)" hits, expected 1"
echo "ok: a committed handoff is still found, so the mistake is catchable"

# --- Deleting the doc clears the signal. ----------------------------------
pushd $ws/feat-a
rm HANDOFF.md
jj commit -m "burn after reading" >/dev/null 2>&1; or begin
    echo >&2 "smoke-handoff: burn commit failed"
    popd
    exit 1
end
popd
$wf handoffs >/dev/null 2>&1
test $status -eq 1; or _fail "deleted handoff still reported as a hit"
echo "ok: burning the doc clears the resume signal"

# --- Argument handling: it always scans everything. -----------------------
$wf handoffs feat-a >/dev/null 2>&1
test $status -eq 2; or _fail "handoffs accepted a NAME argument"
$wf handoffs --help >/dev/null 2>&1
test $status -eq 2; or _fail "handoffs --help did not exit 2"
echo "ok: refuses arguments"

if test $fails -gt 0
    echo >&2 "smoke-handoff: $fails case(s) failed"
    exit 1
end
echo "SMOKE-HANDOFF PASS"
rm -rf $work
