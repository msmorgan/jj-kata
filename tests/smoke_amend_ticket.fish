#!/usr/bin/env fish
# Smoke: `workflow drop --amend-ticket NAME` — the correct ending for a claim that
# turns out to be impossible. The edits the workspace made to its wip ticket must
# come back to the ticket's ORIGINAL triage location as a `tickets: amend SLUG`
# commit on trunk, and the workspace must be gone. Scenario:
#   blocked-x   — claimed from planned/, notes added, dropped --amend-ticket
#   multi-a/b   — one claim owning two tickets (claim --into), both written back
#   coded-x     — ticket notes PLUS code work: refused without --force
#   adhoc-x     — no ticket at all: refused (nothing to amend)
# Fish has no `set -e`; guard every must-pass step with `; or ...`.

set -l tk (path resolve (status dirname)/..)
set -g wf $tk/skills/jj-workflow/scripts/workflow
set -l work (mktemp -d)
set -l coord $work/myproj
set -l ws $coord/.workspaces
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke-amend: jj git init failed"
    exit 1
end
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | (default@ ~ @)' >/dev/null

mkdir -p docs/tickets/planned docs/tickets/bugs
printf '# blocked-x\n\nDo the thing.\n' >docs/tickets/planned/blocked-x.md
printf '# multi-a\n\nA.\n' >docs/tickets/planned/multi-a.md
printf '# multi-b\n\nB.\n' >docs/tickets/bugs/multi-b.md
printf '# coded-x\n\nC.\n' >docs/tickets/planned/coded-x.md
jj commit -m "base" >/dev/null; or begin
    echo >&2 "smoke-amend: base commit failed"
    exit 1
end

# ---------------------------------------------------------------- blocked-x
$wf claim blocked-x >/dev/null 2>&1; or begin
    echo >&2 "smoke-amend: claim blocked-x failed"
    exit 1
end
test -f $ws/blocked-x/docs/tickets/wip/blocked-x.md; or begin
    echo >&2 "smoke-amend: blocked-x ticket not in wip/ inside the workspace"
    exit 1
end
# The agent discovers the work is blocked and writes that into the ticket —
# on disk only, never committed (the common shape).
printf '# blocked-x\n\nDo the thing.\n\nneeds: some-unbuilt-thing\n' \
    >$ws/blocked-x/docs/tickets/wip/blocked-x.md

$wf drop --amend-ticket blocked-x; or begin
    echo >&2 "smoke-amend: drop --amend-ticket blocked-x failed (rc=$status)"
    exit 1
end
test ! -e $ws/blocked-x; or begin
    echo >&2 "smoke-amend: blocked-x workspace dir survived the drop"
    exit 1
end
# Back where it came FROM (planned/), not wip/ and not done/.
test -f docs/tickets/planned/blocked-x.md; or begin
    echo >&2 "smoke-amend: blocked-x did not come back to planned/"
    exit 1
end
test ! -e docs/tickets/wip/blocked-x.md; or begin
    echo >&2 "smoke-amend: blocked-x left behind in wip/"
    exit 1
end
grep -q 'needs: some-unbuilt-thing' docs/tickets/planned/blocked-x.md; or begin
    echo >&2 "smoke-amend: the workspace's ticket edits were not written back"
    exit 1
end
# …as a real, non-empty commit on trunk, and the claim is gone.
test -n "$(jj log --no-graph -r 'description(substring:"tickets: amend blocked-x") & ~empty()' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke-amend: no non-empty 'tickets: amend blocked-x' commit on trunk"
    exit 1
end
not jj bookmark list -T 'name ++ "\n"' | string match -q blocked-x
or begin
    echo >&2 "smoke-amend: blocked-x claim bookmark survived the drop"
    exit 1
end
# The rescue must not resurrect the claim's own work: no `claim blocked-x`
# commit and no wip/ file anywhere on the line.
test -z "$(jj log --no-graph -r 'description(substring:"workflow: claim blocked-x")' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke-amend: the abandoned claim commit survived"
    exit 1
end
echo "ok: drop --amend-ticket writes the wip edits back to the ticket's origin"

# ------------------------------------------------------------- multi-a/b
# One claim owning two tickets from DIFFERENT triage folders — each must go home
# to its own folder, in one commit.
$wf claim multi-a >/dev/null 2>&1; or begin
    echo >&2 "smoke-amend: claim multi-a failed"
    exit 1
end
$wf claim multi-b --into multi-a >/dev/null 2>&1; or begin
    echo >&2 "smoke-amend: claim multi-b --into multi-a failed"
    exit 1
end
printf '# multi-a\n\nA.\n\nneeds: nope-a\n' >$ws/multi-a/docs/tickets/wip/multi-a.md
printf '# multi-b\n\nB.\n\nneeds: nope-b\n' >$ws/multi-a/docs/tickets/wip/multi-b.md
$wf drop --amend-ticket multi-a; or begin
    echo >&2 "smoke-amend: drop --amend-ticket multi-a failed (rc=$status)"
    exit 1
end
grep -q 'needs: nope-a' docs/tickets/planned/multi-a.md; or begin
    echo >&2 "smoke-amend: multi-a edits missing from planned/"
    exit 1
end
grep -q 'needs: nope-b' docs/tickets/bugs/multi-b.md; or begin
    echo >&2 "smoke-amend: multi-b edits missing from bugs/ (its own origin folder)"
    exit 1
end
test -n "$(jj log --no-graph -r 'description(substring:"tickets: amend multi-a, multi-b")' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke-amend: multi-ticket claim did not produce one combined update commit"
    exit 1
end
echo "ok: a multi-ticket claim writes every ticket back to its own origin folder"

# ------------------------------------------------------------- coded-x
# Ticket notes are rescued, but real code work is not — that still blocks the
# drop (exit 2) unless --force is added.
$wf claim coded-x >/dev/null 2>&1; or begin
    echo >&2 "smoke-amend: claim coded-x failed"
    exit 1
end
printf '# coded-x\n\nC.\n\nneeds: nope-c\n' >$ws/coded-x/docs/tickets/wip/coded-x.md
pushd $ws/coded-x
echo half >half-done.txt
jj commit -m "wip: half a feature" >/dev/null; or begin
    echo >&2 "smoke-amend: coded-x commit failed"
    popd
    exit 1
end
popd
$wf drop --amend-ticket coded-x >/dev/null 2>&1
set -l rc $status
test $rc -eq 2; or begin
    echo >&2 "smoke-amend: drop --amend-ticket with code work should refuse with 2 (got $rc)"
    exit 1
end
test -d $ws/coded-x; or begin
    echo >&2 "smoke-amend: refused drop deleted the workspace anyway"
    exit 1
end
# …and --force gets past it, still rescuing the ticket.
$wf drop --amend-ticket --force coded-x; or begin
    echo >&2 "smoke-amend: drop --amend-ticket --force coded-x failed (rc=$status)"
    exit 1
end
grep -q 'needs: nope-c' docs/tickets/planned/coded-x.md; or begin
    echo >&2 "smoke-amend: coded-x edits missing after forced amend-drop"
    exit 1
end
test -z "$(jj log --no-graph -r 'description(substring:"wip: half a feature")' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke-amend: --force did not discard the code work"
    exit 1
end
echo "ok: --amend-ticket rescues tickets but still refuses to discard code work"

# ------------------------------------------------------------- adhoc-x
# An ad-hoc `start` owns no ticket — there is nothing to write back, so the flag
# refuses rather than dropping silently.
$wf start adhoc-x >/dev/null 2>&1; or begin
    echo >&2 "smoke-amend: start adhoc-x failed"
    exit 1
end
$wf drop --amend-ticket adhoc-x >/dev/null 2>&1
set rc $status
test $rc -eq 2; or begin
    echo >&2 "smoke-amend: --amend-ticket on a ticketless workspace should refuse with 2 (got $rc)"
    exit 1
end
test -d $ws/adhoc-x; or begin
    echo >&2 "smoke-amend: refused --amend-ticket dropped the ticketless workspace anyway"
    exit 1
end
# The nonsensical flag pairing is refused too.
$wf drop --integrated --amend-ticket >/dev/null 2>&1
set rc $status
test $rc -eq 2; or begin
    echo >&2 "smoke-amend: 'drop --integrated --amend-ticket' should refuse with 2 (got $rc)"
    exit 1
end
echo "ok: --amend-ticket refuses when there is no ticket to amend"

# ------------------------------------------------------------- unedited
# A claim dropped with --amend-ticket but never actually edited must NOT mint an
# empty-but-described 'tickets: amend' commit (that litter is not auto-pruned).
mkdir -p docs/tickets/planned
printf '# untouched-x\n\nU.\n' >docs/tickets/planned/untouched-x.md
jj commit -m "add untouched-x ticket" >/dev/null; or begin
    echo >&2 "smoke-amend: committing untouched-x ticket failed"
    exit 1
end
$wf claim untouched-x >/dev/null 2>&1; or begin
    echo >&2 "smoke-amend: claim untouched-x failed"
    exit 1
end
$wf drop --amend-ticket untouched-x; or begin
    echo >&2 "smoke-amend: drop --amend-ticket untouched-x failed (rc=$status)"
    exit 1
end
test -z "$(jj log --no-graph -r 'description(substring:"tickets: amend untouched-x")' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke-amend: an unedited ticket minted an empty 'tickets: amend' commit"
    exit 1
end
test -f docs/tickets/planned/untouched-x.md; or begin
    echo >&2 "smoke-amend: untouched-x did not roll back to planned/"
    exit 1
end
echo "ok: an unedited ticket produces no empty update commit"

echo "SMOKE-AMEND PASS"
