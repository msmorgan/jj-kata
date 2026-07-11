#!/usr/bin/env fish
# Smoke: install the toolkit into a throwaway jj repo, start a workspace, integrate it.
# The coordinator dir is deliberately named `myproj`, NOT `default`: the workspace
# NAME is always `default`, but its directory name is the user's choice, and the
# toolkit must resolve it via `jj workspace root --name default` — never `../default`.
# Nesting under $work also keeps feature/.integrated siblings out of the temp root.
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
git config user.email t@t 2>/dev/null
git config user.name t 2>/dev/null

# Ignore patterns for the archive-clean check further down: retiring a workspace
# must strip its ignored/generated files (jj's `git clean -fdX`).
printf '*.tmp\njunk.d/\n' >.gitignore

# Commit the installed scripts so jj tracks them and they propagate to new workspaces.
# (jj workspace add checks out a commit; untracked files stay only in the default WC.)
jj commit -m "install toolkit" >/dev/null; or begin
    echo >&2 "smoke: commit failed"
    exit 1
end

# The default workspace resolves to the renamed coordinator dir, not ../default.
test "$(./scripts/jj workspace root --name default)" = "$coord"; or begin
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
# Ignored junk (per the committed .gitignore) — must NOT survive into the archive.
echo scratch >scratch.tmp
mkdir junk.d
echo blob >junk.d/blob.bin
./scripts/jj describe -m "feat: note" >/dev/null; or begin
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

./scripts/workflow integrate feat-x >/dev/null; or begin
    echo >&2 "smoke: integrate failed"
    exit 1
end
test ! -d ../feat-x; or begin
    echo >&2 "smoke: ../feat-x was not archived after integrate"
    exit 1
end
test -d ../.integrated/feat-x; or begin
    echo >&2 "smoke: ../feat-x did not land in ../.integrated/"
    exit 1
end
echo "ok: workspace archived after integrate"

# The archive keeps tracked work but not ignored junk (jj `git clean -fdX`).
test -f ../.integrated/feat-x/note.txt; or begin
    echo >&2 "smoke: archived workspace lost tracked note.txt"
    exit 1
end
not test -e ../.integrated/feat-x/scratch.tmp
and not test -e ../.integrated/feat-x/junk.d
or begin
    echo >&2 "smoke: ignored junk survived into the archive"
    exit 1
end
echo "ok: ignored files stripped from archive"
echo "SMOKE PASS"
