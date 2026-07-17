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
# not register as "work" anywhere (abandon's refusal check, integrate).
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

# Plain abandon must refuse while feat-x still holds un-integrated work.
./scripts/workflow abandon feat-x >/dev/null 2>&1
and begin
    echo >&2 "smoke: plain abandon dropped un-integrated work"
    exit 1
end
test -d ../feat-x; or begin
    echo >&2 "smoke: refused abandon still deleted the workspace dir"
    exit 1
end
echo "ok: plain abandon refuses un-integrated work"

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

# Post-integrate plain abandon drops it (the claim bookmark is gone).
./scripts/workflow abandon feat-x >/dev/null 2>&1; or begin
    echo >&2 "smoke: post-integrate abandon failed (rc=$status)"
    exit 1
end
test ! -e ../feat-x; or begin
    echo >&2 "smoke: ../feat-x still exists after abandon"
    exit 1
end
echo "ok: plain abandon retires integrated workspace"

# Regression: `abandon --force` sweeps ONLY `default@..NAME@ | NAME` — foreign
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
./scripts/workflow abandon --force feat-y >/dev/null 2>&1; or begin
    echo >&2 "smoke: abandon --force feat-y failed"
    exit 1
end
# feat-y's own work is gone…
jj log --no-graph -r $w_id -T '' --ignore-working-copy >/dev/null 2>&1
and begin
    echo >&2 "smoke: feat-y work survived --force abandon"
    exit 1
end
# …but feat-z's commit survives, reparented past the abandoned stack.
jj log --no-graph -r $z_id -T '' --ignore-working-copy >/dev/null 2>&1; or begin
    echo >&2 "smoke: abandon --force swept foreign feat-z commit"
    exit 1
end
echo "ok: abandon --force bounded to its own stack"

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
echo "SMOKE PASS"
