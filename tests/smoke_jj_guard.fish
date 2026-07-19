#!/usr/bin/env fish
# Smoke: the PreToolUse(Bash) jj-guard. Feeds harness-shaped payloads to the
# hook and asserts exit code. Two halves: commands that MUST be allowed (real
# git/config text living inside quoted DATA, plus ordinary jj usage) and
# commands that MUST be blocked (git as a command, jj bypass flags, and the
# quote/backslash EVASION forms the guard is expressly hardened against).

set -l tk (path resolve (status dirname)/..)
set -l hook $tk/scripts/hooks/jj_guard.fish
set -l work (mktemp -d)
cd $work; or exit 1
jj git init >/dev/null 2>&1; or begin; echo >&2 "smoke-guard: jj init failed"; exit 1; end

function _run --argument-names hook cwd cmd
    set -l payload (jq -n --arg cwd $cwd --arg c $cmd \
        '{tool_name:"Bash", cwd:$cwd, tool_input:{command:$c}}')
    printf '%s' $payload | fish $hook >/dev/null 2>&1
    echo $status
end

function _run_gemini --argument-names hook cwd cmd
    set -l payload (jq -n --arg cwd $cwd --arg c $cmd \
        '{conversationId:"abc-123", workspacePaths:[$cwd], toolCall:{name:"run_command", args:{CommandLine:$c, Cwd:$cwd}}, stepIndex:0}')
    set -l out (printf '%s' $payload | fish $hook 2>&1)
    set -l rc $status
    if test "$rc" != 0
        echo "error-rc-$rc"
    else
        echo $out | jq -r '.decision // "null"'
    end
end

set -l fails 0

# --- MUST ALLOW: git/--config/--ignore-immutable as DATA, and normal usage. ---
set -l allow \
    "jj diff --git" \
    "jj diff --git -r @-" \
    "jj show --git @" \
    "jj describe -m 'see; git blame for context'" \
    "jj commit -m 'use --config to override the default'" \
    "jj commit -m 'document the --ignore-immutable footgun'" \
    "jj describe -m 'fix(git): parity with git output'" \
    "jj log -r 'main@git'" \
    "jj bookmark list --all-remotes" \
    "jj git push" \
    "jj git fetch --all-remotes" \
    "jj diff --git | delta" \
    "jj log | grep git" \
    "rg 'git' README.md" \
    "cat .gitignore" \
    "echo hello && jj st" \
    "foo --config=x; jj st" \
    'echo "the git tool is nice"' \
    'jj describe -m "literal \$(git log) is escaped"' \
    "jj st"
for c in $allow
    set -l rc (_run $hook $work $c)
    if test "$rc" != 0
        echo >&2 "smoke-guard (Claude): MUST-ALLOW blocked (rc=$rc): $c"
        set fails (math $fails + 1)
    end
    set -l dec (_run_gemini $hook $work $c)
    if test "$dec" != "allow"
        echo >&2 "smoke-guard (Gemini): MUST-ALLOW blocked (decision=$dec): $c"
        set fails (math $fails + 1)
    end
end

# --- MUST BLOCK: real git commands, jj bypass flags, and evasion forms. ---
set -l block \
    "git status" \
    "git commit -m x" \
    "cd foo && git push" \
    "ls; git log" \
    "/usr/bin/git status" \
    "sudo git clean -fd" \
    "(git status)" \
    "jj --config ui.color=never st" \
    "jj st --ignore-immutable" \
    "jj --config-file /tmp/x.toml log" \
    "jj --config=ui.color=never st" \
    "\"git\" status" \
    "jj \"--ignore-immutable\" st" \
    "jj --'config' ui.x=y st" \
    "gi't' status" \
    'echo "$(git push)"' \
    'echo "`git status`"' \
    'jj log && echo "out: $(git rev-parse HEAD)"'
for c in $block
    set -l rc (_run $hook $work $c)
    if test "$rc" != 2
        echo >&2 "smoke-guard (Claude): MUST-BLOCK allowed (rc=$rc): $c"
        set fails (math $fails + 1)
    end
    set -l dec (_run_gemini $hook $work $c)
    if test "$dec" != "deny"
        echo >&2 "smoke-guard (Gemini): MUST-BLOCK allowed (decision=$dec): $c"
        set fails (math $fails + 1)
    end
end

# --- Non-jj repo: guard must stay out of the way entirely. ---
set -l outside (mktemp -d)
set -l rc (_run $hook $outside "git status")
if test "$rc" != 0
    echo >&2 "smoke-guard (Claude): git blocked OUTSIDE a jj repo (rc=$rc)"
    set fails (math $fails + 1)
end
set -l dec (_run_gemini $hook $outside "git status")
if test "$dec" != "allow"
    echo >&2 "smoke-guard (Gemini): git blocked OUTSIDE a jj repo (decision=$dec)"
    set fails (math $fails + 1)
end

if test $fails -gt 0
    echo >&2 "smoke-guard: $fails case(s) failed"
    exit 1
end
echo "ok: jj-guard allows data/normal usage, blocks git + bypass flags + evasion"
