#!/usr/bin/env fish
# Install the jj-workflow toolkit into a target repo.
#   install.fish [--copy] TARGET_REPO
# Default: symlink each script (so updates here propagate). --copy: independent copies.

argparse copy -- $argv
or exit 2

set -l target $argv[1]
if test -z "$target"; or not test -d "$target"
    echo >&2 "usage: install.fish [--copy] TARGET_REPO (an existing directory)"
    exit 2
end

set -l here (path resolve (status dirname))
set -l src $here/scripts
set target (path resolve $target)

set -l mode symlink
set -q _flag_copy; and set mode copy

mkdir -p "$target/scripts/hooks" "$target/scripts/lib"
for f in (find $src -type f)
    set -l rel (string replace "$src/" '' $f)
    set -l dest "$target/scripts/$rel"
    mkdir -p (path dirname "$dest")
    if test "$mode" = copy
        cp "$f" "$dest"
    else
        ln -sfn "$f" "$dest"
    end
end

# Drop the example config so the follow-up below is actionable.
cp "$here/jjworkflow.example.toml" "$target/jjworkflow.example.toml"

# Immutability lives in repo config, not a wrapper: the default line is immutable
# from every feature workspace, open in the `default` coordinator. `@` resolves
# per-workspace, so this one shared alias yields per-workspace behavior.
#   immutable_heads() = builtin_immutable_heads() | (default@ ~ @)
# In `default`, default@ ~ @ is empty -> coordinator open. In a feature workspace
# it is default@ -> the whole trunk/claim line is protected.
set -l alias_set 1
jj -R "$target" config set --repo \
    'revset-aliases."immutable_heads()"' 'builtin_immutable_heads() | (default@ ~ @)'
or set alias_set 0

echo "Installed toolkit ($mode) into $target/scripts/"
if test $alias_set = 1
    echo "Set repo config: immutable_heads() = builtin_immutable_heads() | (default@ ~ @)"
else
    echo >&2 "ERROR: could not set the immutable_heads() alias — the repo has NO trunk"
    echo >&2 "protection until it is set. Set it by hand, then re-check with 'jj config list --repo':"
    echo >&2 "    jj -R $target config set --repo 'revset-aliases.\"immutable_heads()\"' \\"
    echo >&2 "      'builtin_immutable_heads() | (default@ ~ @)'"
end
echo
echo "Manual follow-ups:"
echo "  1. Register the PreToolUse(Bash) guard scripts/hooks/jj_guard.fish in the"
echo "     target's Claude settings (.claude/settings.json), and set env JJ_EDITOR=false"
echo "     there (the toolkit always passes -m; this is a belt-and-braces guard)."
echo "  2. If step 'Set repo config' above did not run, set the alias yourself:"
echo "       jj config set --repo 'revset-aliases.\"immutable_heads()\"' \\"
echo "         'builtin_immutable_heads() | (default@ ~ @)'"
echo "  3. If defaults don't fit, copy jjworkflow.example.toml -> jjworkflow.toml and edit."
echo "  4. Add a scripts/provision-workspace hook if new workspaces need shared dirs."

# An install without the immutability alias is NOT a success: any feature
# workspace could rewrite the shared trunk line with plain jj commands. The
# scripts are in place, but exit nonzero so automation can't scroll past it.
test $alias_set = 1
or exit 1
