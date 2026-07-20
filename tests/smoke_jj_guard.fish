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

function _rewrite_codex --argument-names hook root cwd cmd
    set -l payload (jq -n --arg cwd $cwd --arg c $cmd \
        '{tool_name:"Bash", cwd:$cwd, tool_input:{command:$c}}')
    set -l out (printf '%s' $payload | env PLUGIN_ROOT=$root fish $hook 2>&1)
    set -l rc $status
    if test "$rc" != 0
        echo "error-rc-$rc"
    else
        echo $out | jq -r \
            'select(.hookSpecificOutput.hookEventName == "PreToolUse")
             | select(.hookSpecificOutput.permissionDecision == "allow")
             | .hookSpecificOutput.updatedInput.command'
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

# --- Codex: every allowed Bash call gets the plugin's bin/ on PATH. ----------
set -l original 'printf "%s\n" "$PATH"; command -v workflow; command -v conflicts'
set -l rewritten (_rewrite_codex $hook $tk $outside $original | string collect)
if test -z "$rewritten"; or string match -q 'error-rc-*' -- $rewritten
    echo >&2 "smoke-guard (Codex): allowed command was not rewritten"
    set fails (math $fails + 1)
else
    set -l codex_out (env PATH=/usr/bin:/bin bash -c "$rewritten")
    set -l codex_rc $status
    if test "$codex_rc" != 0
        echo >&2 "smoke-guard (Codex): rewritten command failed (rc=$codex_rc)"
        set fails (math $fails + 1)
    else if test "$codex_out[1]" != "$tk/bin:/usr/bin:/bin"
        echo >&2 "smoke-guard (Codex): bin/ was not prepended to PATH: $codex_out[1]"
        set fails (math $fails + 1)
    else if test "$codex_out[2]" != "$tk/bin/workflow"
        echo >&2 "smoke-guard (Codex): workflow did not resolve from plugin bin/: $codex_out[2]"
        set fails (math $fails + 1)
    else if test "$codex_out[3]" != "$tk/bin/conflicts"
        echo >&2 "smoke-guard (Codex): conflicts did not resolve from plugin bin/: $codex_out[3]"
        set fails (math $fails + 1)
    end
end

# The same rewrite is applied inside a jj repo, where the tools are used.
set rewritten (_rewrite_codex $hook $tk $work 'command -v workflow' | string collect)
set -l resolved (env PATH=/usr/bin:/bin bash -c "$rewritten")
if test "$resolved" != "$tk/bin/workflow"
    echo >&2 "smoke-guard (Codex): workflow was not exposed inside a jj repo: $resolved"
    set fails (math $fails + 1)
end

# PLUGIN_ROOT can contain shell metacharacters; the rewrite must quote it.
set -l odd_root "$outside/a path's plugin"
mkdir -p "$odd_root/bin"
ln -s $tk/bin/workflow "$odd_root/bin/workflow"
set rewritten (_rewrite_codex $hook "$odd_root" $outside 'command -v workflow' | string collect)
set resolved (env PATH=/usr/bin:/bin bash -c "$rewritten")
if test "$resolved" != "$odd_root/bin/workflow"
    echo >&2 "smoke-guard (Codex): PLUGIN_ROOT was not shell-quoted safely: $resolved"
    set fails (math $fails + 1)
end

# A denied command must remain denied rather than receiving a rewrite.
set rewritten (_rewrite_codex $hook $tk $work "git status" | string collect)
if test "$rewritten" != "error-rc-2"
    echo >&2 "smoke-guard (Codex): blocked command was rewritten: $rewritten"
    set fails (math $fails + 1)
end

if test $fails -gt 0
    echo >&2 "smoke-guard: $fails case(s) failed"
    exit 1
end
echo "ok: jj-guard enforces policy and exposes plugin bin/ to Codex"
