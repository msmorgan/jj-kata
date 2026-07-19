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

echo "SMOKE PASS"
