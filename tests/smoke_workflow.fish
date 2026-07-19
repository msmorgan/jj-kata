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

./scripts/workflow start feat-x; or begin
    echo >&2 "smoke: workflow start failed"
    exit 1
end
test -d ../feat-x; or begin
    echo >&2 "smoke: ../feat-x was not created"
    exit 1
end
echo "ok: workspace ../feat-x created"

pushd ../feat-x
echo hello >note.txt
# Ignored junk (per the committed .gitignore) — must not count as work.
echo scratch >scratch.tmp
mkdir junk.d
echo blob >junk.d/blob.bin
jj describe -m "feat: note" >/dev/null; or begin
    echo >&2 "smoke: describe failed"
    popd
    exit 1
end
# refresh from INSIDE the child workspace, no NAME — must be allowed (guard) and
# succeed (detach path; a no-op here since trunk hasn't advanced).
./scripts/workflow refresh; or begin
    echo >&2 "smoke: refresh from child workspace failed"
    popd
    exit 1
end
echo "ok: refresh from child workspace"
popd

# Plain drop must refuse while feat-x still holds un-integrated work.
./scripts/workflow drop feat-x >/dev/null 2>&1
and begin
    echo >&2 "smoke: plain drop dropped un-integrated work"
    exit 1
end
test -d ../feat-x; or begin
    echo >&2 "smoke: refused drop still deleted the workspace dir"
    exit 1
end
echo "ok: plain drop refuses un-integrated work"

./scripts/workflow integrate feat-x >/dev/null 2>&1; or begin
    echo >&2 "smoke: integrate failed"
    exit 1
end
# Integrate keeps the workspace, its WC parked as a fresh change on the
# integrated tip (default@-).
test -d ../feat-x; or begin
    echo >&2 "smoke: workspace dir gone after integrate (should be kept)"
    exit 1
end
jj workspace list -T 'name ++ "\n"' | string match -q feat-x
or begin
    echo >&2 "smoke: workspace no longer registered after integrate"
    exit 1
end
test "$(jj log --no-graph -r 'feat-x@-' -T 'change_id.short()' --ignore-working-copy)" \
    = "$(jj log --no-graph -r '@-' -T 'change_id.short()' --ignore-working-copy)"
or begin
    echo >&2 "smoke: feat-x@ not parked on default@-"
    exit 1
end
echo "ok: integrate keeps workspace, WC parked on default@-"

# An ad-hoc claim that never adopted a ticket is ELIDED from trunk at integrate
# — no empty "start feat-x" link left in the integrated chain.
test -z "$(jj log --no-graph -r 'description("start feat-x")' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke: empty 'start feat-x' claim commit survived integrate"
    exit 1
end
echo "ok: empty ad-hoc claim elided at integrate"

# Post-integrate plain drop drops it (the claim bookmark is gone).
./scripts/workflow drop feat-x >/dev/null 2>&1; or begin
    echo >&2 "smoke: post-integrate drop failed (rc=$status)"
    exit 1
end
test ! -e ../feat-x; or begin
    echo >&2 "smoke: ../feat-x still exists after drop"
    exit 1
end
echo "ok: plain drop retires integrated workspace"

# Regression: `drop --force` sweeps ONLY `default@..NAME@ | NAME` — foreign
# work stacked on top of the doomed feature must survive (2026-07-16 incident:
# the old unbounded `roots()::` sweep followed descendants into another
# feature's commits).
./scripts/workflow start feat-y >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-y failed"
    exit 1
end
pushd ../feat-y
echo y1 >y.txt
jj commit -m "feat-y work" >/dev/null; or begin
    echo >&2 "smoke: feat-y commit failed"
    popd
    exit 1
end
set -l w_id (jj log --no-graph -r @- -T 'change_id.short()')
popd
./scripts/workflow start feat-z >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-z failed"
    exit 1
end
pushd ../feat-z
echo z1 >z.txt
jj commit -m "feat-z work" >/dev/null; or begin
    echo >&2 "smoke: feat-z commit failed"
    popd
    exit 1
end
set -l z_id (jj log --no-graph -r @- -T 'change_id.short()')
# Stack feat-z's commit on top of feat-y's work — simulating any state where
# foreign commits sit above the doomed stack.
jj rebase -r $z_id -d $w_id >/dev/null; or begin
    echo >&2 "smoke: stacking feat-z on feat-y failed"
    popd
    exit 1
end
popd
./scripts/workflow drop --force feat-y >/dev/null 2>&1; or begin
    echo >&2 "smoke: drop --force feat-y failed"
    exit 1
end
# feat-y's own work is gone…
jj log --no-graph -r $w_id -T '' --ignore-working-copy >/dev/null 2>&1
and begin
    echo >&2 "smoke: feat-y work survived --force drop"
    exit 1
end
# …but feat-z's commit survives, reparented past the droped stack.
jj log --no-graph -r $z_id -T '' --ignore-working-copy >/dev/null 2>&1; or begin
    echo >&2 "smoke: drop --force swept foreign feat-z commit"
    exit 1
end
echo "ok: drop --force bounded to its own stack"

# Regression: default-side line rewrites bank other workspaces' un-snapshotted
# edits first (__snapshot_workspaces) — otherwise the rewrite rebases a stale
# WC commit and the edit gets re-snapshotted into the hidden predecessor by
# that workspace's next command (working-copy divergence).
./scripts/workflow start feat-p >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-p failed"
    exit 1
end
pushd ../feat-p
echo p1 >p.txt
jj commit -m "feat-p work" >/dev/null; or begin
    echo >&2 "smoke: feat-p commit failed"
    popd
    exit 1
end
popd
./scripts/workflow start feat-w >/dev/null 2>&1; or begin
    echo >&2 "smoke: start feat-w failed"
    exit 1
end
# Un-snapshotted edit: no jj command touches feat-w after this write.
echo dirty >../feat-w/dirty.txt
# feat-w's claim sits above feat-p's, so integrating feat-p reorders the line
# under feat-w — the staleness event under test.
./scripts/workflow integrate feat-p >/dev/null 2>&1; or begin
    echo >&2 "smoke: integrate feat-p failed"
    exit 1
end
jj diff -r feat-w@ --name-only | string match -q dirty.txt
or begin
    echo >&2 "smoke: feat-w's un-snapshotted edit missing from its WC commit after reorder"
    exit 1
end
echo "ok: default-side rewrite banks other workspaces' edits first"

# --help must print usage and NOT start a feature; a dash-leading NAME is refused.
./scripts/workflow start --help >/dev/null 2>&1
and begin
    echo >&2 "smoke: 'start --help' should exit non-zero (usage), not succeed"
    exit 1
end
test ! -e ../--help; or begin
    echo >&2 "smoke: 'start --help' created a feature workspace named --help"
    exit 1
end
not jj bookmark list -T 'name ++ "\n"' | string match -q -- --help
or begin
    echo >&2 "smoke: 'start --help' created a bookmark named --help"
    exit 1
end
echo "ok: 'start --help' prints usage instead of starting a feature"

# Regression: a pre-existing __tip bookmark must NOT wedge creation (the old
# fixed-name `jj bookmark create __tip` failed "already exists").
jj bookmark create __tip -r @ >/dev/null 2>&1
./scripts/workflow start feat-tip >/dev/null 2>&1; or begin
    echo >&2 "smoke: start wedged by a pre-existing __tip bookmark"
    exit 1
end
test -d ../feat-tip; or begin
    echo >&2 "smoke: feat-tip workspace not created"
    exit 1
end
# We must not have clobbered the user's __tip.
jj bookmark list -T 'name ++ "\n"' | string match -q -- __tip
or begin
    echo >&2 "smoke: start removed the pre-existing __tip bookmark"
    exit 1
end
echo "ok: start no longer depends on a __tip bookmark"

# Regression: an agent that hand-rolls the completion — moves its ticket wip->done
# AND titles the feature commit "complete NAME" — must NOT get a second, EMPTY
# "complete NAME" appended by integrate (that empty-but-described dup is not
# auto-pruned; the `xyz|sxx` duplicate-complete incident, 2026-07-19).
mkdir -p docs/tickets/planned
echo "# ticket bug-x" >docs/tickets/planned/bug-x.md
jj commit -m "add bug-x ticket" >/dev/null; or begin
    echo >&2 "smoke: committing bug-x ticket failed"
    exit 1
end
./scripts/workflow claim bug-x >/dev/null 2>&1; or begin
    echo >&2 "smoke: claim bug-x failed"
    exit 1
end
pushd ../bug-x
echo work >bug-x-work.txt
# The agent does integrate's job itself: move the ticket to done/ and title the
# commit "complete bug-x". done/ isn't tracked yet (empty dirs don't propagate),
# so create it before the move.
mkdir -p docs/tickets/done
mv docs/tickets/wip/bug-x.md docs/tickets/done/bug-x.md; or begin
    echo >&2 "smoke: agent-side ticket move failed"
    popd
    exit 1
end
jj describe -m "complete bug-x" >/dev/null; or begin
    echo >&2 "smoke: describe bug-x failed"
    popd
    exit 1
end
popd
./scripts/workflow integrate bug-x >/dev/null 2>&1; or begin
    echo >&2 "smoke: integrate bug-x failed"
    exit 1
end
# No EMPTY commit described "complete bug-x" may exist on trunk.
test -z "$(jj log --no-graph -r 'description(substring:"complete bug-x") & empty()' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke: integrate minted an empty duplicate 'complete bug-x' commit"
    exit 1
end
# The real, non-empty completion (carrying the work + wip->done move) survives.
test -n "$(jj log --no-graph -r 'description(substring:"complete bug-x") & ~empty()' -T 'change_id' --ignore-working-copy)"
or begin
    echo >&2 "smoke: real 'complete bug-x' commit missing after integrate"
    exit 1
end
echo "ok: no empty duplicate 'complete NAME' when agent pre-moves the ticket"

echo "SMOKE PASS"
