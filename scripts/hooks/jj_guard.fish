#!/usr/bin/env fish
# scripts/hooks/jj_guard.fish — PreToolUse(Bash) guard for a jj-workflow repo.
#
# Immutability itself now lives in repo config, not a wrapper:
#   immutable_heads() = builtin_immutable_heads() | (default@ ~ @)
# `@` resolves per-workspace, so that one shared alias locks the whole default
# line from every FEATURE workspace while leaving the `default` coordinator open
# (there default@ ~ @ is empty). jj is invoked directly. This hook is the single
# enforcement layer, with two bans:
#   1. git — this is a jj repo; git mutations corrupt/confuse the state.
#   2. jj with --config / --config-file / --ignore-immutable — the three flags
#      that would override the immutable_heads guard.
#
# Exit 2 + stderr blocks the tool call; exit 0 allows it. Anything we can't parse
# is allowed (don't interfere with non-Bash tools or malformed payloads).

# One jq pass: emit cwd (first line) then the command, only for Bash payloads.
# A non-Bash tool (or malformed payload) yields nothing → nothing matches.
set -l out (jq -r 'select(.tool_name == "Bash") | (.cwd // ""), (.tool_input.command // "")')
set -l cwd $out[1]
set -l cmd $out[2..]

# A plugin install enables this hook in EVERY project — act only inside a jj
# repo. Walk up from the command's cwd (falling back to the hook's own) looking
# for a .jj dir; anywhere else, git is none of our business.
test -n "$cwd"; or set cwd $PWD
set -l d $cwd
while not test -d "$d/.jj"
    set -l parent (path dirname $d)
    test "$parent" = "$d"; and exit 0    # hit the filesystem root: not a jj repo
    set d $parent
end

# Match against a DE-QUOTED copy of the command: shell quoting is invisible to a
# raw-text regex, so `"git" …`, `jj "--ignore-immutable"` or `jj --'config'`
# would slip past patterns anchored on whitespace. Stripping quote/backslash
# characters mirrors what the shell's own tokenizer concatenates (`gi't'` → git;
# `'git'x` → gitx, still unmatched — correctly, since the shell would run gitx).
# A quoted string carrying such text as DATA (a commit message mentioning
# --config) may now false-positive; for a guard, fail-closed is the right bias.
set -l flat (string replace -a -- '\\' '' $cmd | string replace -a -- "'" '' | string replace -a -- '"' '')

# Command position: start of line, or after ; & | && || ( or a
# command/exec/sudo/… wrapper, with an optional path prefix.
set -l cmdpos '(?:^|&&|\|\||[;&|\n(])\s*(?:(?:command|exec|builtin|env|sudo|time|nice|nohup|xargs)\s+)*(?:[^\s;&|()`]*/)?'

# git at a command position: refused outright. `jj git push` is fine — there
# `git` follows `jj`, which isn't a command-position wrapper, so it won't match.
if string match -rq -- $cmdpos'git(?:\s|$)' $flat
    echo >&2 "jj-guard: git is banned in this jj repo — use jj, not git."
    exit 2
end

# A jj invocation carrying a guard-bypassing flag is refused. Scoped to commands
# that actually invoke jj, so an unrelated tool's --config elsewhere is ignored.
if string match -rq -- $cmdpos'jj(?:\s|$)' $flat
    if set -l flag (string match -r -- '(?:^|\s)(--ignore-immutable|--config(?:-file)?)(?:[=\s]|$)' $flat)
        echo >&2 "jj-guard: refusing $flag[2] — it would bypass the repo's immutable_heads guard."
        exit 2
    end
end

exit 0
