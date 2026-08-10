#!/usr/bin/env fish

# Working-copy divergence is the toolkit's worst failure mode: two visible
# commits share one change id, and the affected workspace's on-disk edits are
# silently swapped out from under whoever was typing in it.
#
# It needs exactly one precondition, verified by bisecting the factors: a
# workspace that is BOTH stale AND dirty when `jj workspace update-stale` runs.
# update-stale then snapshots those edits against the workspace's stale
# operation head, forking the op log; the reconcile leaves two successors.
# Stale-but-clean is safe, and dirty-but-banked-first is safe.
#
# Two guarantees are asserted here:
#   A. The toolkit never LEAVES a workspace stale after rewriting the shared
#      default line — that is what creates the first half of the precondition.
#   B. When a workspace is stale anyway (an interrupted command, a crash, a
#      long-parked "floating cursor"), a default-line rewrite LEAVES IT ALONE
#      and still succeeds. It cannot be banked (jj declines to snapshot a stale
#      working copy) and must not be un-staled — that is the diverging step — so
#      it is skipped by both halves. It must NOT block the operation: a parked
#      workspace is a normal thing to keep around.

set -l tk (path dirname (path resolve (status filename)))/..
set -g wf $tk/skills/jj-workflow/scripts/workflow
set -g cf $tk/skills/jj-workflow/scripts/conflicts
set -l work (mktemp -d)
set -l coord $work/coord
set -l ws $coord/.workspaces

function _fail --argument-names msg
    echo >&2 "smoke-divergence: $msg"
    exit 1
end

# Is WS_DIR's working copy stale? A bare jj command there is the ground truth.
function _is_stale --argument-names ws_dir
    command jj -R "$ws_dir" status 2>&1 | string match -q '*working copy is stale*'
end

mkdir -p $coord; or exit 1
cd $coord; or exit 1
jj git init --colocate >/dev/null 2>&1; or _fail "jj git init failed"
jj config set --repo 'revset-aliases."all_if_any(rev)"' 'descendants(ancestors(rev))' >/dev/null
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | ((working_copies() ~ @) & all_if_any(default@ ~ @))' >/dev/null
printf 'base\n' > f.txt
jj commit -m "base" >/dev/null; or _fail "base commit failed"

$wf start feat-a >/dev/null 2>&1; or _fail "start feat-a"
$wf start feat-b >/dev/null 2>&1; or _fail "start feat-b"

# --- A. A shared-line rewrite must not leave a SIBLING stale. ---------------
# `refresh NAME` from default reorders NAME's claim under default@, rebasing the
# rest of the line — including feat-b's working-copy commit — as it goes. If the
# path banks but never un-stales, feat-b is left stale and is now one stray edit
# away from diverging on the next integrate.
$wf refresh feat-a >/dev/null 2>&1; or _fail "refresh feat-a failed"
_is_stale $ws/feat-b
and _fail "refresh left sibling feat-b STALE — one edit there now diverges on the next rewrite"
_is_stale $ws/feat-a
and _fail "refresh left its own target feat-a STALE"
echo "ok: refresh leaves no workspace stale"

# `drop` rewrites the shared line too (it abandons the claim and its stack).
$wf drop feat-a >/dev/null 2>&1; or _fail "drop feat-a failed"
_is_stale $ws/feat-b
and _fail "drop left sibling feat-b STALE"
echo "ok: drop leaves no workspace stale"

# --- B. Stale AND dirty must REFUSE, not diverge. ---------------------------
# Manufacture the state behind the toolkit's back, the way an interrupted
# command or a crash would: rewrite feat-b's WC commit from default without
# un-staling it, then edit a file in it.
$wf start feat-c >/dev/null 2>&1; or _fail "start feat-c"
cd $coord
printf 'trunk2\n' > g.txt
jj commit -m trunk2 >/dev/null; or _fail "trunk2 commit failed"
jj rebase -r 'feat-b@' -d '@-' >/dev/null 2>&1; or _fail "manual rebase of feat-b@ failed"
_is_stale $ws/feat-b; or _fail "setup did not make feat-b stale — the test proves nothing"
printf 'PRECIOUS EDIT\n' > $ws/feat-b/f.txt

# feat-c is a clean, ordinary workspace; integrating it rewrites the shared line
# and would drag stale-and-dirty feat-b through update-stale. It must be
# refreshed onto the moved trunk first (P2), or integrate refuses for that
# unrelated reason and this test proves nothing about divergence.
cd $ws/feat-c
printf 'c work\n' > c.txt
jj commit -m "c work" >/dev/null; or _fail "feat-c commit failed"
$wf refresh >/dev/null 2>&1; or _fail "refresh feat-c failed"
set -l out ($wf integrate 2>&1)
set -l rc $status
cd $coord

# The whole point: a stale sibling must not hold the operation hostage.
test $rc -eq 0
or _fail "integrate was blocked (rc=$rc) by a stale sibling — a parked workspace must not block it: $out"

set -l div (jj log -r 'divergent()' --no-graph -T 'change_id.short() ++ "\n"' --ignore-working-copy)
test (count $div) -eq 0
or _fail "integrate produced a DIVERGENT change: $div"

test "$(cat $ws/feat-b/f.txt)" = "PRECIOUS EDIT"
or _fail "feat-b's on-disk edit was swapped out from under it"

# Left exactly as found — still stale, for its own session to repair.
_is_stale $ws/feat-b
or _fail "integrate un-staled feat-b; skipping it is what avoids the divergence"

string match -q -r 'feat-b' -- $out
or _fail "integrate did not mention the skipped workspace: $out"
echo "ok: a stale sibling is left untouched, does not block, and does not diverge"

# --- B2. A stale but CLEAN parked workspace ("floating cursor") is the common
# case and must be equally inert: no divergence, and above all no blocking. ---
$wf start feat-park >/dev/null 2>&1; or _fail "start feat-park"
$wf start feat-d >/dev/null 2>&1; or _fail "start feat-d"
cd $coord
printf 'trunk3\n' > h.txt
jj commit -m trunk3 >/dev/null; or _fail "trunk3 commit failed"
jj rebase -r 'feat-park@' -d '@-' >/dev/null 2>&1; or _fail "manual rebase of feat-park@ failed"
_is_stale $ws/feat-park; or _fail "setup did not make feat-park stale"

cd $ws/feat-d
printf 'd work\n' > d.txt
jj commit -m "d work" >/dev/null; or _fail "feat-d commit failed"
$wf refresh >/dev/null 2>&1; or _fail "refresh feat-d failed"
$wf integrate >/dev/null 2>&1
or _fail "a stale but CLEAN parked workspace blocked integrate"
cd $coord
set -l div3 (jj log -r 'divergent()' --no-graph -T 'change_id.short() ++ "\n"' --ignore-working-copy)
test (count $div3) -eq 0; or _fail "a clean parked workspace still diverged: $div3"
echo "ok: a clean parked workspace neither blocks integrate nor diverges"

# --- C. And `repair` must actually be the recovery the skip defers to. ------
cd $ws/feat-b
$wf repair >/dev/null 2>&1; or _fail "repair failed on the stale-and-dirty workspace"
cd $coord
set -l div2 (jj log -r 'divergent()' --no-graph -T 'change_id.short() ++ "\n"' --ignore-working-copy)
test (count $div2) -eq 0; or _fail "repair left a divergence behind: $div2"
test "$(cat $ws/feat-b/f.txt)" = "PRECIOUS EDIT"
or _fail "repair lost the workspace's on-disk edit"
echo "ok: repair heals the stale-and-dirty workspace and keeps its edit"

echo "SMOKE-DIVERGENCE PASS"
