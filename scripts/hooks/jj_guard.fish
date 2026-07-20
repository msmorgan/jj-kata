#!/usr/bin/env fish
# scripts/hooks/jj_guard.fish — PreToolUse(Bash) guard for a jj-workflow repo.
#
# Codex and Claude Code both send the documented tool_name/tool_input payload.
# Google Antigravity uses the toolCall payload handled below.
#
# Immutability itself lives in repo config, not a wrapper:
#   immutable_heads() = builtin_immutable_heads() | (default@ ~ @)
# `@` resolves per-workspace, so that one shared alias locks the whole default
# line from every FEATURE workspace while leaving the `default` coordinator open
# (there default@ ~ @ is empty). jj is invoked directly. This hook is the single
# enforcement layer, with two bans:
#   1. git — this is a jj repo; git mutations corrupt/confuse the state.
#   2. jj with --config / --config-file / --ignore-immutable — the flags that
#      would override the immutable_heads guard.
#
# Exit 2 + stderr blocks the tool call; exit 0 allows it. Anything we can't parse
# is allowed (don't interfere with non-Bash tools or malformed payloads).
#
# MATCHING — why a real tokenizer and not a flat regex.
# The earlier guard stripped all quote/backslash chars and regex-scanned the
# result. That defeats quote EVASION (`"git"`, `jj --'config'`, `g\it`) but it
# cannot tell a real `; git` from the SAME characters sitting inside a quoted
# argument, so ordinary messages false-positived:
#   jj describe -m 'see; git blame for context'   → "git is banned"
#   jj commit  -m 'use --config to override'       → "refusing --config"
# We now tokenize with shell quote-awareness instead. Quotes/backslashes are
# consumed WITHIN a token (so `"git"` → token `git`, still banned; `g\it` → git;
# `jj --'config'` → token --config, still refused — evasion stays closed), while
# a `git`/`--config` embedded in a larger quoted argument is one token of DATA,
# never a command word or a standalone flag, so it is allowed. Command
# substitution (`$(...)`, backticks) — even inside double quotes — is scanned as
# its own command list, so `echo "$(git push)"` is still caught. The git ban
# keys only off tokens at a COMMAND POSITION; the flag ban is scoped per simple
# command to the tokens of an actual `jj` invocation.
#
# Fail-closed residue (rare, acceptable): a message that is EXACTLY a bypass flag
# (`jj commit -m '--config'`) still refuses, and `jj foo -- --config` treats the
# positional as a flag. Both are contrived; the common message case is fixed.

# Read stdin payload
set -l payload (cat | string join \n)

# Codex does not currently add a plugin's bin/ directory to ordinary shell
# commands. Plugin hooks do receive PLUGIN_ROOT, though, and PreToolUse may
# rewrite Bash input. On every allowed Codex shell call, prepend this plugin's
# bin/ to PATH inside the command itself. This makes `workflow` and `conflicts`
# resolve without modifying the user's shell startup files. Claude does not set
# PLUGIN_ROOT; Gemini has its own allow/deny response shape.
function _jjg_allow --argument-names cmd is_bash_hook is_gemini
    if test "$is_gemini" = "true"
        echo '{"decision": "allow"}'
    else if test "$is_bash_hook" = "true"; and set -q PLUGIN_ROOT; and test -n "$PLUGIN_ROOT"
        jq -n --arg bin "$PLUGIN_ROOT/bin" --arg command "$cmd" \
            '{hookSpecificOutput:{
                hookEventName:"PreToolUse",
                permissionDecision:"allow",
                updatedInput:{
                    command:("export PATH=" + ($bin | @sh) + ":\"$PATH\"\n" + $command)
                }
            }}'
    end
end

# Detect payload shape. Codex deliberately uses the Claude-compatible Bash
# shape, so this branch serves both hosts.
set -l is_bash_hook (echo "$payload" | jq -r 'if .tool_name == "Bash" then "true" else "false" end')
set -l is_gemini (echo "$payload" | jq -r 'if .toolCall.name == "run_command" then "true" else "false" end')

if test "$is_bash_hook" != "true" -a "$is_gemini" != "true"
    # Not a supported terminal-tool payload; let it pass.
    exit 0
end

set -l cwd ""
set -l cmd ""
if test "$is_bash_hook" = "true"
    set cwd (echo "$payload" | jq -r '.cwd // ""')
    set cmd (echo "$payload" | jq -r '.tool_input.command // ""')
else if test "$is_gemini" = "true"
    set cwd (echo "$payload" | jq -r '.toolCall.args.Cwd // ""')
    # If Cwd is empty or null, fall back to workspacePaths[0]
    if test -z "$cwd" -o "$cwd" = "null"
        set cwd (echo "$payload" | jq -r '.workspacePaths[0] // ""')
    end
    set cmd (echo "$payload" | jq -r '.toolCall.args.CommandLine // ""')
end

# A plugin install enables this hook in EVERY project — act only inside a jj
# repo. Walk up from the command's cwd (falling back to the hook's own) looking
# for a .jj dir; anywhere else, git is none of our business.
test -n "$cwd" -a "$cwd" != "null"; or set cwd $PWD
set -l d $cwd
while not test -d "$d/.jj"
    set -l parent (path dirname $d)
    if test "$parent" = "$d"
        # Not a jj repo: allow execution
        _jjg_allow "$cmd" "$is_bash_hook" "$is_gemini"
        exit 0
    end
    set d $parent
end

# Cheap over-approximate pre-filter: nothing can be blocked unless the command
# mentions git / --config / --ignore-immutable even after quote+backslash noise
# is removed. Most commands mention none of them → allow without tokenizing. The
# flatten here only WIDENS (it may false-positive, e.g. `digit`), never narrows,
# so no evasion slips past: the precise verdict is still the tokenizer's.
set -l probe (string replace -a -- '\\' '' $cmd | string replace -a -- "'" '' | string replace -a -- '"' '')
if not string match -rq -- 'git|--config|--ignore-immutable' -- $probe
    _jjg_allow "$cmd" "$is_bash_hook" "$is_gemini"
    exit 0
end

# --- Precise pass: tokenize `cmd` respecting shell quoting. -----------------
# Emits two parallel arrays: tt = decoded token text, tp = "1" if the token
# opened at a command position (start of a command list, or right after an
# unquoted ; | & ( newline, or at the head of a $()/backtick substitution),
# else "0". State machine over a mode STACK so nested quotes and command
# substitution pop back to the right context. Token/command-position state is
# kept in globals so small open/close helpers can mutate it.
set -g tt
set -g tp
set -g tok ''      # current token text (decoded)
set -g intok 0     # 1 while a token is open
set -g curpos 0    # command-position flag captured when the current token opened
set -g armed 1     # 1 = the next token to open is at a command position

function _jjg_open   # ensure a token is open, snapshotting its command position
    if test $intok -eq 0
        set -g curpos $armed
        set -g armed 0
        set -g intok 1
    end
end
function _jjg_close  # flush an open token (may be an empty '' token)
    if test $intok -eq 1
        set -ga tt $tok
        set -ga tp $curpos
        set -g tok ''
        set -g intok 0
    end
end

set -l NL (printf '\n')
set -l TAB (printf '\t')
set -l BT (printf '\140')          # backtick
set -l chars (string split '' -- $cmd)
set -l len (count $chars)
set -l st norm                     # mode stack; top = $st[-1]: norm sub bt sq dq
set -l i 1
while test $i -le $len
    set -l c $chars[$i]
    set -l cur $st[-1]
    if test "$cur" = sq
        # single quotes: everything literal until the closing '
        if test "$c" = "'"; set -e st[-1]; else; _jjg_open; set -g tok $tok$c; end
    else if test "$cur" = dq
        # double quotes: literal DATA, except \ escapes and $(/` open a sub-scan
        if test "$c" = '"'
            set -e st[-1]
        else if test "$c" = '\\'
            set i (math $i + 1); test $i -le $len; and begin; _jjg_open; set -g tok $tok$chars[$i]; end
        else if test "$c" = "$BT"
            _jjg_close; set -g armed 1; set -a st bt
        else if test "$c" = '$'; and test (math $i + 1) -le $len; and test "$chars["(math $i + 1)"]" = '('
            _jjg_close; set -g armed 1; set -a st sub; set i (math $i + 1)
        else
            _jjg_open; set -g tok $tok$c
        end
    else
        # command-scanning context: norm (top level / subshell), sub ($()), bt (``)
        if test "$c" = "'"
            _jjg_open; set -a st sq
        else if test "$c" = '"'
            _jjg_open; set -a st dq
        else if test "$c" = '\\'
            _jjg_open; set i (math $i + 1); test $i -le $len; and set -g tok $tok$chars[$i]
        else if test "$c" = '$'; and test (math $i + 1) -le $len; and test "$chars["(math $i + 1)"]" = '('
            _jjg_close; set -g armed 1; set -a st sub; set i (math $i + 1)
        else if test "$c" = "$BT"
            if test "$cur" = bt
                _jjg_close; set -g armed 0; set -e st[-1]
            else
                _jjg_close; set -g armed 1; set -a st bt
            end
        else if test "$c" = ')'
            if test "$cur" = sub
                _jjg_close; set -g armed 0; set -e st[-1]     # end $() — continuation
            else
                _jjg_close; set -g armed 1                    # subshell close
            end
        else if test "$c" = ' '; or test "$c" = "$TAB"
            _jjg_close                                        # word break, same command
        else if test "$c" = ';'; or test "$c" = '|'; or test "$c" = '&'; or test "$c" = '('; or test "$c" = "$NL"
            _jjg_close; set -g armed 1                        # command separator
        else
            _jjg_open; set -g tok $tok$c
        end
    end
    set i (math $i + 1)
end
_jjg_close   # flush a trailing open token

# --- Decide per simple command. --------------------------------------------
# `command`, `sudo`, … are wrappers: the real command word is the next token even
# though it sits at a non-command position.
set -l wrappers command exec builtin env sudo time nice nohup xargs
set -l ntok (count $tt)
set -l curcmd ''           # command word of the simple command in progress
set -l expectword 0       # 1 = still resolving the command word (past wrappers)
set -l j 1
while test $j -le $ntok
    set -l text $tt[$j]
    if test "$tp[$j]" = 1
        set expectword 1
        set curcmd ''
    end
    if test $expectword -eq 1
        if contains -- $text $wrappers
            set j (math $j + 1); continue   # wrapper — keep looking
        end
        set curcmd $text
        set expectword 0
        if test "$text" = git; or string match -rq -- '/git$' -- $text
            if test "$is_bash_hook" = "true"
                echo >&2 "jj-guard: git is banned in this jj repo — use jj, not git."
                exit 2
            else
                echo '{"decision": "deny", "reason": "git is banned in this jj repo — use jj, not git."}'
                exit 0
            end
        end
        set j (math $j + 1); continue
    end
    # argument token of curcmd — only jj's own flags can bypass the guard
    if test "$curcmd" = jj; or string match -rq -- '/jj$' -- $curcmd
        if contains -- $text --ignore-immutable --config --config-file
            if test "$is_bash_hook" = "true"
                echo >&2 "jj-guard: refusing $text — it would bypass the repo's immutable_heads guard."
                exit 2
            else
                echo "{\"decision\": \"deny\", \"reason\": \"refusing $text — it would bypass the repo's immutable_heads guard.\"}"
                exit 0
            end
        else if set -l m (string match -r -- '^(--config|--config-file)=' -- $text)
            if test "$is_bash_hook" = "true"
                echo >&2 "jj-guard: refusing $m[2] — it would bypass the repo's immutable_heads guard."
                exit 2
            else
                echo "{\"decision\": \"deny\", \"reason\": \"refusing $m[2] — it would bypass the repo's immutable_heads guard.\"}"
                exit 0
            end
        end
    end
    set j (math $j + 1)
end

_jjg_allow "$cmd" "$is_bash_hook" "$is_gemini"
exit 0
