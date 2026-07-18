#!/usr/bin/env fish
# Smoke: `workflow drop --integrated` sweeps every integrated, empty feature
# workspace and NOTHING else. The scenario builds four workspaces:
#   feat-a, feat-b — start + integrate, left parked (integrated, empty)  → SWEPT
#   feat-c         — ad-hoc start, never integrated (bookmark present)   → KEPT
#   feat-d         — integrated, then resumed with new committed work    → KEPT
# --dry-run must report but delete nothing; the argparse guards must refuse
# the nonsensical flag combinations. Fish has no `set -e`; guard every must-pass
# step with `; or ...`.

set -l tk (path resolve (status dirname)/..)
set -l work (mktemp -d)
set -l coord $work/myproj
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init --colocate >/dev/null; or begin
    echo >&2 "smoke-sweep: jj git init failed"
    exit 1
end
$tk/install.fish $coord >/dev/null; or begin
    echo >&2 "smoke-sweep: install failed"
    exit 1
end
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke-sweep: commit failed"
    exit 1
end

# start + integrate NAME, leaving the workspace parked (integrated, empty).
function _start_integrate --argument-names name
    ./scripts/workflow start $name >/dev/null 2>&1; or return 1
    ./scripts/workflow integrate $name >/dev/null 2>&1; or return 1
end

_start_integrate feat-a; or begin; echo >&2 "smoke-sweep: setup feat-a failed"; exit 1; end
_start_integrate feat-b; or begin; echo >&2 "smoke-sweep: setup feat-b failed"; exit 1; end

# feat-c: ad-hoc start, never integrated — its claim bookmark still exists, so
# it is NOT integrated and must survive the sweep.
./scripts/workflow start feat-c >/dev/null 2>&1; or begin
    echo >&2 "smoke-sweep: start feat-c failed"
    exit 1
end

# feat-d: integrate, then resume with real committed work. Bookmark is gone
# (integrated) but default@..feat-d@ now holds non-empty work → must be KEPT.
_start_integrate feat-d; or begin; echo >&2 "smoke-sweep: setup feat-d failed"; exit 1; end
pushd ../feat-d
command jj workspace update-stale >/dev/null 2>&1
echo resumed >resumed.txt
jj commit -m "feat-d follow-up work" >/dev/null; or begin
    echo >&2 "smoke-sweep: feat-d follow-up commit failed"
    popd
    exit 1
end
popd

# All four dirs exist going in.
for d in feat-a feat-b feat-c feat-d
    test -d ../$d; or begin
        echo >&2 "smoke-sweep: ../$d missing before sweep"
        exit 1
    end
end

# --- argparse guards: nonsensical combinations must be refused (exit 2). ---
./scripts/workflow drop --integrated feat-a >/dev/null 2>&1
and begin; echo >&2 "smoke-sweep: --integrated with a NAME was accepted"; exit 1; end
./scripts/workflow drop --integrated --force >/dev/null 2>&1
and begin; echo >&2 "smoke-sweep: --integrated --force was accepted"; exit 1; end
./scripts/workflow drop --dry-run feat-a >/dev/null 2>&1
and begin; echo >&2 "smoke-sweep: --dry-run without --integrated was accepted"; exit 1; end
# A refused guard must not have deleted anything.
test -d ../feat-a; or begin; echo >&2 "smoke-sweep: guard refusal still deleted feat-a"; exit 1; end
echo "ok: --integrated argparse guards refuse bad combos"

# --- dry-run: reports, deletes nothing. ---
./scripts/workflow drop --integrated --dry-run >/dev/null 2>&1; or begin
    echo >&2 "smoke-sweep: dry-run exited non-zero"
    exit 1
end
for d in feat-a feat-b feat-c feat-d
    test -d ../$d; or begin
        echo >&2 "smoke-sweep: dry-run deleted ../$d"
        exit 1
    end
end
echo "ok: --dry-run deletes nothing"

# --- the real sweep: exactly feat-a and feat-b go. ---
./scripts/workflow drop --integrated >/dev/null 2>&1; or begin
    echo >&2 "smoke-sweep: drop --integrated exited non-zero"
    exit 1
end
test ! -e ../feat-a; or begin; echo >&2 "smoke-sweep: feat-a survived the sweep"; exit 1; end
test ! -e ../feat-b; or begin; echo >&2 "smoke-sweep: feat-b survived the sweep"; exit 1; end
test -d ../feat-c; or begin; echo >&2 "smoke-sweep: feat-c (un-integrated) was swept"; exit 1; end
test -d ../feat-d; or begin; echo >&2 "smoke-sweep: feat-d (resumed work) was swept"; exit 1; end
# The swept workspaces are gone from jj's registry too.
jj workspace list -T 'name ++ "\n"' | string match -q feat-a
and begin; echo >&2 "smoke-sweep: feat-a still registered after sweep"; exit 1; end
echo "ok: drop --integrated sweeps exactly the integrated, empty workspaces"

# A second sweep with nothing eligible is a clean no-op (exit 0).
./scripts/workflow drop --integrated >/dev/null 2>&1; or begin
    echo >&2 "smoke-sweep: empty sweep exited non-zero"
    exit 1
end
echo "ok: empty sweep is a clean no-op"

echo "SMOKE-SWEEP PASS"
