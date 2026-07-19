#!/usr/bin/env fish
# Smoke: install the toolkit into a throwaway jj repo, start a workspace, integrate it.
# The coordinator dir is deliberately named `myproj`, NOT `default`: the workspace
# NAME is always `default`, but its directory name is the user's choice, and the
# toolkit must resolve it via `jj workspace root --name default` — never `../default`.
# Nesting under $work also keeps feature-workspace siblings out of the temp root.
# Fish has no `set -e`, so each step that must succeed is guarded with `; or ...`.

set -l tk (path resolve (status dirname)/..)
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke: jj git init failed"
    exit 1
end
$tk/install.fish $coord >/dev/null; or begin
    echo >&2 "smoke: install failed"
    exit 1
end

# Ignore patterns for the junk files created below: ignored build litter must
# not register as "work" anywhere (drop's refusal check, integrate).
printf '*.tmp\njunk.d/\n' >.gitignore

# Commit the installed scripts so jj tracks them and they propagate to new workspaces.
# (jj workspace add checks out a commit; untracked files stay only in the default WC.)
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke: commit failed"
    exit 1
end

# The default workspace resolves to the renamed coordinator dir, not ../default.
test "$(jj workspace root --name default)" = "$coord"; or begin
    echo >&2 "smoke: workspace root --name default != $coord"
    exit 1
end
echo "ok: default workspace maps to renamed dir myproj/"

# --- Positive control: with a linear (single-parent) default@, a no-arg refresh
# from inside a feature workspace succeeds (P1 must not reject the normal case). ---
./scripts/workflow start feat-ok >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-ok failed"
    exit 1
end
pushd ../feat-ok
echo hello >note.txt
jj describe -m "feat: note" >/dev/null 2>&1; or begin
    echo >&2 "smoke: describe feat-ok failed"
    popd
    exit 1
end
./scripts/workflow refresh >/dev/null 2>&1
set -l rc_ok $status
popd
test $rc_ok -eq 0; or begin
    echo >&2 "smoke: refresh refused on a linear default@ (rc=$rc_ok)"
    exit 1
end
echo "ok: P1 allows refresh when default@ is linear"

# --- P1 negative: a merge default@ must make refresh refuse with a clear message. ---
./scripts/workflow start feat-m >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-m failed"
    exit 1
end
# Turn default@ into a genuine 2-parent merge, from the coordinator (default) WC.
# These are NEW commits above trunk (not immutable rewrites), so the guard allows
# their creation; the resulting default@- resolving to two commits is what the P1
# check keys on. `@` here IS default@ (cwd is the coordinator).
set -l tip (jj log --no-graph -r 'default@-' -T 'change_id.short()' --ignore-working-copy)
jj new "$tip" -m sideA >/dev/null 2>&1; set -l a (jj log --no-graph -r @ -T 'change_id.short()')
jj new "$tip" -m sideB >/dev/null 2>&1; set -l b (jj log --no-graph -r @ -T 'change_id.short()')
jj new "$a" "$b" -m "merge (test)" >/dev/null 2>&1; or begin
    echo >&2 "smoke: could not construct a merge default@"
    exit 1
end
# Sanity: default@- now resolves to two commits.
test (count (jj log --no-graph -r 'default@-' -T 'change_id.short() ++ "\n"' --ignore-working-copy)) -eq 2; or begin
    echo >&2 "smoke: default@ is not a 2-parent merge as expected"
    exit 1
end
pushd ../feat-m
./scripts/workflow refresh >/dev/null 2>&1
set -l rc $status
popd
test $rc -ne 0; or begin
    echo >&2 "smoke: refresh did not refuse on a merge default@ (rc=$rc)"
    exit 1
end
echo "ok: P1 refuses refresh when default@ is a merge"

# --- Task 4: two-tier guard — a feature workspace may act on ITSELF, but not on
# a sibling, and creation stays coordinator-only. Task 3's section left default@
# a merge in the temp repo above, so we start a FRESH temp repo here. ---
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke: jj git init failed (task4)"
    exit 1
end
$tk/install.fish $coord >/dev/null; or begin
    echo >&2 "smoke: install failed (task4)"
    exit 1
end
printf '*.tmp\njunk.d/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke: commit failed (task4)"
    exit 1
end
test "$(jj workspace root --name default)" = "$coord"; or begin
    echo >&2 "smoke: workspace root --name default != $coord (task4)"
    exit 1
end
echo "ok: task4 fresh coordinator maps to renamed dir myproj/"

# Cross-feature refused: a feature ws may not integrate a sibling.
./scripts/workflow start feat-b >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-b failed"
    exit 1
end
./scripts/workflow start feat-c >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-c failed"
    exit 1
end
pushd ../feat-b
./scripts/workflow integrate feat-c >/dev/null 2>&1
set -l rc_cross $status
popd
test $rc_cross -ne 0; or begin
    echo >&2 "smoke: integrating a sibling (feat-c) from feat-b was allowed (rc=$rc_cross)"
    exit 1
end
echo "ok: cross-feature op refused from a feature workspace"

# Creation still default-only: `start` from inside a feature ws must be refused.
pushd ../feat-b
./scripts/workflow start anything >/dev/null 2>&1
set -l rc_start $status
popd
test $rc_start -ne 0; or begin
    echo >&2 "smoke: 'start' from a feature workspace was allowed (rc=$rc_start)"
    exit 1
end
echo "ok: creation (start) still refused from a feature workspace"

# --- Task 5A: integrate FROM a feature workspace (self), no NAME. Fresh temp repo
# so nothing from the guard sections above pollutes the trunk line. ---
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke: jj git init failed (task5A)"
    exit 1
end
$tk/install.fish $coord >/dev/null; or begin
    echo >&2 "smoke: install failed (task5A)"
    exit 1
end
printf '*.tmp\njunk.d/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke: commit failed (task5A)"
    exit 1
end
test "$(jj workspace root --name default)" = "$coord"; or begin
    echo >&2 "smoke: workspace root --name default != $coord (task5A)"
    exit 1
end
echo "ok: task5A fresh coordinator maps to renamed dir myproj/"

# Start feat-int with committed work, then integrate it FROM INSIDE with no NAME.
./scripts/workflow start feat-int >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-int"
    exit 1
end
pushd ../feat-int
echo work >w.txt
jj describe -m "feat: real work" >/dev/null
set -l work_id (jj log --no-graph -r @ -T 'change_id.short()')
./scripts/workflow integrate >/dev/null 2>&1; or begin
    echo >&2 "smoke: self-integrate failed"
    popd
    exit 1
end
popd
# The work's change id is now an ancestor of default@ (trunk advanced).
test -n "$(jj log --no-graph -r "$work_id"' & ::default@' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke: feat-int's work is not an ancestor of default@ after self-integrate"
    exit 1
end
# feat-int@ parked on default@- (integrated tip).
test "$(jj log --no-graph -r 'feat-int@-' -T 'change_id.short()' --ignore-working-copy)" \
    = "$(jj log --no-graph -r 'default@-' -T 'change_id.short()' --ignore-working-copy)"
or begin
    echo >&2 "smoke: feat-int not parked on default@- after self-integrate"
    exit 1
end
echo "ok: self-integrate advances trunk and parks the workspace"

# --- Task 5B: P2 gate — a feature behind ADVANCED trunk (real work above) must be
# refused until refreshed. Fresh temp repo. ---
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke: jj git init failed (task5B)"
    exit 1
end
$tk/install.fish $coord >/dev/null; or begin
    echo >&2 "smoke: install failed (task5B)"
    exit 1
end
printf '*.tmp\njunk.d/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke: commit failed (task5B)"
    exit 1
end
test "$(jj workspace root --name default)" = "$coord"; or begin
    echo >&2 "smoke: workspace root --name default != $coord (task5B)"
    exit 1
end
echo "ok: task5B fresh coordinator maps to renamed dir myproj/"

./scripts/workflow start feat-old >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-old"
    exit 1
end
./scripts/workflow start feat-new >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-new"
    exit 1
end
# Integrate feat-new (self) — advances trunk with REAL work, leaving feat-old behind.
pushd ../feat-new
echo n >n.txt
jj describe -m "feat: n" >/dev/null
./scripts/workflow integrate >/dev/null 2>&1; or begin
    echo >&2 "smoke: integrate feat-new (setup for P2) failed"
    popd
    exit 1
end
popd
# feat-old is now behind the advanced trunk — a self-integrate must REFUSE.
pushd ../feat-old
echo o >o.txt
jj describe -m "feat: o" >/dev/null
./scripts/workflow integrate >/dev/null 2>&1
set -l rc $status
popd
test $rc -ne 0; or begin
    echo >&2 "smoke: integrate of a stale feature was allowed (P2)"
    exit 1
end
echo "ok: P2 refuses a stale feature"
# …and after refresh it succeeds.
pushd ../feat-old
./scripts/workflow refresh >/dev/null 2>&1
./scripts/workflow integrate >/dev/null 2>&1
set -l rc2 $status
popd
test $rc2 -eq 0; or begin
    echo >&2 "smoke: integrate after refresh still refused (rc=$rc2)"
    exit 1
end
echo "ok: P2 accepts a refreshed feature"

# --- Task 5C: the combined advance splice must keep the trunk line linear —
# default@- (the integrated tip) must not become a redundant-parent merge. Fresh
# temp repo. ---
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke: jj git init failed (task5C)"
    exit 1
end
$tk/install.fish $coord >/dev/null; or begin
    echo >&2 "smoke: install failed (task5C)"
    exit 1
end
printf '*.tmp\njunk.d/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke: commit failed (task5C)"
    exit 1
end
test "$(jj workspace root --name default)" = "$coord"; or begin
    echo >&2 "smoke: workspace root --name default != $coord (task5C)"
    exit 1
end
echo "ok: task5C fresh coordinator maps to renamed dir myproj/"

./scripts/workflow start feat-c >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-c"
    exit 1
end
pushd ../feat-c
echo c >c.txt
jj describe -m "feat: c" >/dev/null
./scripts/workflow integrate >/dev/null 2>&1; or begin
    echo >&2 "smoke: integrate feat-c failed"
    popd
    exit 1
end
popd
# After integrate the coordinator's integrated tip must have exactly one parent:
# fork_point(default@-) == default@- iff default@- is a single (non-merge) commit.
test -n "$(jj log --no-graph -r 'default@- & fork_point(default@-)' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke: default@- is a merge after integrate (redundant-parent splice)"
    exit 1
end
# And the whole coordinator line is linear (no commit with >1 parent).
test -z "$(jj log --no-graph -r '::default@ & merges()' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke: a merge commit exists on the coordinator line after integrate"
    exit 1
end
echo "ok: advance splice keeps the trunk line linear"

# --- Task 5D: a sibling workspace's un-snapshotted edit must survive a
# self-integrate (__snapshot_workspaces banks every ws first, even when integrate
# is launched from a feature ws). Fresh temp repo. ---
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke: jj git init failed (task5D)"
    exit 1
end
$tk/install.fish $coord >/dev/null; or begin
    echo >&2 "smoke: install failed (task5D)"
    exit 1
end
printf '*.tmp\njunk.d/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke: commit failed (task5D)"
    exit 1
end
test "$(jj workspace root --name default)" = "$coord"; or begin
    echo >&2 "smoke: workspace root --name default != $coord (task5D)"
    exit 1
end
echo "ok: task5D fresh coordinator maps to renamed dir myproj/"

./scripts/workflow start feat-s1 >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-s1"
    exit 1
end
pushd ../feat-s1
echo s1 >s1.txt
jj commit -m "s1 work" >/dev/null
popd
./scripts/workflow start feat-s2 >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-s2"
    exit 1
end
# Un-snapshotted edit in feat-s2 — no jj command touches feat-s2 after this write.
echo dirty >../feat-s2/dirty.txt
# Self-integrate feat-s1 from inside it; feat-s2's WC must be banked first.
pushd ../feat-s1
./scripts/workflow refresh >/dev/null 2>&1
./scripts/workflow integrate >/dev/null 2>&1; or begin
    echo >&2 "smoke: self-integrate feat-s1 failed"
    popd
    exit 1
end
popd
jj diff -r feat-s2@ --name-only | string match -q dirty.txt
or begin
    echo >&2 "smoke: sibling feat-s2's un-snapshotted edit lost after self-integrate"
    exit 1
end
echo "ok: self-integrate banks sibling workspaces' edits (no divergence)"

# --- Task 5E: a TICKETED claim integrated from inside its own feature workspace
# must move its ticket wip/->done/ on trunk AND record a `complete <slug>` commit.
# Every other case here uses ad-hoc `start` (empty slugs), so __integrate_steps'
# `__check_todo` move + `jj commit -m "complete …"` branch is otherwise never
# exercised. Fresh temp repo — prior blocks leave the trunk line dirty. ---
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke: jj git init failed (task5E)"
    exit 1
end
$tk/install.fish $coord >/dev/null; or begin
    echo >&2 "smoke: install failed (task5E)"
    exit 1
end
printf '*.tmp\njunk.d/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke: commit failed (task5E)"
    exit 1
end
test "$(jj workspace root --name default)" = "$coord"; or begin
    echo >&2 "smoke: workspace root --name default != $coord (task5E)"
    exit 1
end
echo "ok: task5E fresh coordinator maps to renamed dir myproj/"

# Ticketed integrate from the feature ws: wip -> done move + "complete" commit land on trunk.
mkdir -p docs/tickets/planned
printf -- '---\nneeds: []\n---\n# t-real\n' > docs/tickets/planned/t-real.md
jj commit -m "add ticket t-real" >/dev/null
./scripts/workflow claim t-real >/dev/null 2>&1; or begin echo >&2 "smoke: claim t-real failed"; exit 1; end
test -f docs/tickets/wip/t-real.md; or begin echo >&2 "smoke: t-real not in wip/ after claim"; exit 1; end
pushd ../t-real
echo realwork > r.txt
jj describe -m "feat: real work" >/dev/null
./scripts/workflow integrate >/dev/null 2>&1; or begin echo >&2 "smoke: ticketed self-integrate failed"; popd; exit 1; end
popd
# The wip->done move is now on trunk...
test -f docs/tickets/done/t-real.md; or begin echo >&2 "smoke: t-real not moved to done/ after integrate"; exit 1; end
test ! -f docs/tickets/wip/t-real.md; or begin echo >&2 "smoke: t-real still in wip/ after integrate"; exit 1; end
# ...as a 'complete t-real' commit in default@'s ancestry. jj appends a trailing
# newline to `-m` descriptions, so exact:/default match fails on jj 0.43 — a
# substring match asserts the same "completion commit is in ancestry" fact.
test -n "$(jj log --no-graph -r 'description(substring:"complete t-real") & ::default@' -T 'change_id' --ignore-working-copy)"
or begin echo >&2 "smoke: no 'complete t-real' commit on trunk after integrate"; exit 1; end
echo "ok: ticketed self-integrate moves wip->done and records a completion commit"

# --- Task 6: `claim T` from INSIDE a feature workspace folds T into THIS
# workspace's own claim (no --into, no cd), and the claim commit's description
# accretes to `claim <a>, <b>` in wip order. Also guards that a plain fresh
# single claim still describes its claim exactly `claim <slug>` (no double-
# describe weirdness). Fresh temp repo — prior blocks leave the trunk dirty. ---
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke: jj git init failed (task6)"
    exit 1
end
$tk/install.fish $coord >/dev/null; or begin
    echo >&2 "smoke: install failed (task6)"
    exit 1
end
printf '*.tmp\njunk.d/\n' >.gitignore
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke: commit failed (task6)"
    exit 1
end
test "$(jj workspace root --name default)" = "$coord"; or begin
    echo >&2 "smoke: workspace root --name default != $coord (task6)"
    exit 1
end
echo "ok: task6 fresh coordinator maps to renamed dir myproj/"

# Two triage tickets to claim + fold.
mkdir -p docs/tickets/planned
printf -- '---\nneeds: []\n---\n# t-alpha\n' > docs/tickets/planned/t-alpha.md
printf -- '---\nneeds: []\n---\n# t-beta\n'  > docs/tickets/planned/t-beta.md
jj commit -m "add triage tickets t-alpha t-beta" >/dev/null

# Fresh single claim from default: creates the workspace AND describes the claim
# exactly `claim t-alpha` (fresh-claim path must stay intact after the accretion
# change — no "claim t-alpha, t-alpha", no leftover "start t-alpha").
./scripts/workflow claim t-alpha >/dev/null 2>&1; or begin echo >&2 "smoke: claim t-alpha failed (task6)"; exit 1; end
test -f docs/tickets/wip/t-alpha.md; or begin echo >&2 "smoke: t-alpha not in wip/ after claim (task6)"; exit 1; end
test "$(jj log --no-graph -r t-alpha -T 'description.first_line()' --ignore-working-copy)" = "claim t-alpha"
or begin echo >&2 "smoke: fresh single claim did not describe the claim 'claim t-alpha' (task6)"; exit 1; end
echo "ok: task6 fresh single claim describes the claim exactly 'claim t-alpha'"

# Self-fold: from INSIDE the feature ws, `claim t-beta` (no --into) folds t-beta
# into t-alpha's OWN claim. Assert the wip/ files from inside the ws — its
# checkout is the one this op advanced (default's WC goes stale, as with a
# `claim --into`, so its on-disk tree lags until update-stale).
pushd ../t-alpha
./scripts/workflow claim t-beta >/dev/null 2>&1; or begin echo >&2 "smoke: self-fold claim t-beta failed (task6)"; popd; exit 1; end
test -f docs/tickets/wip/t-alpha.md -a -f docs/tickets/wip/t-beta.md
or begin echo >&2 "smoke: both tickets not in wip/ after self-fold (task6)"; popd; exit 1; end
popd

# The claim now owns both tickets and its description accreted, in wip order.
test "$(jj log --no-graph -r t-alpha -T 'description.first_line()' --ignore-working-copy)" = "claim t-alpha, t-beta"
or begin echo >&2 "smoke: claim description did not accrete to 'claim t-alpha, t-beta' (task6)"; exit 1; end
echo "ok: task6 claim folds into self from a feature ws and accretes the description"

echo "SMOKE PASS"
