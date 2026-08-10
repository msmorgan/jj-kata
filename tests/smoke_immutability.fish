#!/usr/bin/env fish
# Smoke: the immutability alias protects features FROM EACH OTHER without
# closing the coordinator out. Four cases, all on one repo with two features:
#   from feat-a → rewrite feat-b@   REFUSED (sibling's working copy)
#   from feat-a → rewrite default@  REFUSED (trunk line)
#   from feat-a → rewrite own work  ALLOWED
#   from default → rewrite feat-b@  ALLOWED  ← the regression that matters:
#     integrate/refresh/drop all rewrite `default@..NAME@`, which INCLUDES
#     NAME@. Gate the sibling clause wrong and every coordinator op dies with
#     "Commit … is immutable".
# Fish has no `set -e`; guard every must-pass step with `; or ...`.

set -l tk (path resolve (status dirname)/..)
set -g wf $tk/skills/jj-workflow/scripts/workflow
set -l work (mktemp -d)
set -l coord $work/myproj
set -l ws $coord/.workspaces
set -l log $work/out.log
mkdir -p $coord; or exit 1
cd $coord; or exit 1

jj git init >/dev/null 2>&1; or begin
    echo >&2 "smoke-immutable: jj init failed"
    exit 1
end
jj config set --repo 'revset-aliases."all_if_any(rev)"' 'descendants(ancestors(rev))' >/dev/null
jj config set --repo 'revset-aliases."immutable_heads()"' \
    'builtin_immutable_heads() | ((working_copies() ~ @) & all_if_any(default@ ~ @))' >/dev/null
echo A >f.txt
jj commit -m "base" >/dev/null 2>&1; or begin
    echo >&2 "smoke-immutable: base commit failed"
    exit 1
end

for name in feat-a feat-b
    $wf start $name >/dev/null 2>&1; or begin
        echo >&2 "smoke-immutable: start $name failed"
        exit 1
    end
end

# --- What the alias RESOLVES to, per workspace -------------------------------
# Before exercising any rewrite: the set itself must differ by context, or the
# four cases below could pass for the wrong reason.
set -l imm_default (jj log --no-graph -r 'immutable_heads() & working_copies()' \
    -T 'change_id.short() ++ "\n"' --ignore-working-copy)
test (count $imm_default) -eq 0; or begin
    echo >&2 "smoke-immutable: coordinator sees working copies as immutable: $imm_default"
    exit 1
end
echo "ok: from default, no working copy is immutable"

pushd $ws/feat-a; or exit 1
set -l imm_feat (jj log --no-graph -r 'immutable_heads() & working_copies()' \
    -T 'change_id.short() ++ "\n"' --ignore-working-copy)
test (count $imm_feat) -eq 2; or begin
    echo >&2 "smoke-immutable: feat-a should see 2 immutable working copies (default@, feat-b@), saw "(count $imm_feat)": $imm_feat"
    popd
    exit 1
end
set -l imm_own (jj log --no-graph -r 'immutable_heads() & @' \
    -T 'change_id.short() ++ "\n"' --ignore-working-copy)
test (count $imm_own) -eq 0; or begin
    echo >&2 "smoke-immutable: feat-a's OWN working copy came back immutable: $imm_own"
    popd
    exit 1
end
echo "ok: from feat-a, default@ and feat-b@ are immutable but @ is not"

# --- Case 1: a feature cannot rewrite its SIBLING ----------------------------
jj describe -r 'feat-b@' -m "hijacked by feat-a" >$log 2>&1
and begin
    echo >&2 "smoke-immutable: feat-a rewrote feat-b's working copy"
    popd
    exit 1
end
grep -qi immutable $log; or begin
    echo >&2 "smoke-immutable: sibling refusal was not an immutability error: "(cat $log)
    popd
    exit 1
end
# Abandon takes the same path — the ban is on rewriting, not on one verb.
jj abandon -r 'feat-b@' >$log 2>&1
and begin
    echo >&2 "smoke-immutable: feat-a abandoned feat-b's working copy"
    popd
    exit 1
end
echo "ok: feat-a cannot describe or abandon feat-b@"

# --- Case 2: a feature cannot rewrite the trunk line -------------------------
jj describe -r 'default@' -m "hijacked by feat-a" >$log 2>&1
and begin
    echo >&2 "smoke-immutable: feat-a rewrote default@"
    popd
    exit 1
end
grep -qi immutable $log; or begin
    echo >&2 "smoke-immutable: default@ refusal was not an immutability error: "(cat $log)
    popd
    exit 1
end
echo "ok: feat-a cannot rewrite default@"

# --- Case 3: a feature CAN rewrite its own stack -----------------------------
echo work >a.txt
jj commit -m "feat-a work" >/dev/null 2>&1; or begin
    echo >&2 "smoke-immutable: feat-a commit failed"
    popd
    exit 1
end
jj describe -r '@-' -m "feat-a work, reworded" >/dev/null 2>&1; or begin
    echo >&2 "smoke-immutable: feat-a could not rewrite its OWN commit"
    popd
    exit 1
end
echo "ok: feat-a can still rewrite its own commits"
popd

# --- Case 4: the coordinator CAN rewrite a feature ---------------------------
# The real toolkit op first: integrate rewrites `default@..feat-a@`, feat-a@
# included. This is what a mis-gated sibling clause breaks.
$wf integrate feat-a >$log 2>&1; or begin
    echo >&2 "smoke-immutable: integrate feat-a failed from the coordinator: "(cat $log)
    exit 1
end
set -l landed (jj log --no-graph -r '::default@ & subject(exact:"feat-a work, reworded")' \
    -T 'change_id.short() ++ "\n"' --ignore-working-copy)
test (count $landed) -eq 1; or begin
    echo >&2 "smoke-immutable: feat-a's commit is not in the trunk line after integrate (found "(count $landed)")"
    exit 1
end
echo "ok: coordinator integrated feat-a (rewrote feat-a@ in the process)"

# …and the bare rewrite, so the permission is shown directly and not only
# through a command that could have reached it some other way.
jj describe -r 'feat-b@' -m "coordinator reword" >$log 2>&1; or begin
    echo >&2 "smoke-immutable: coordinator could not rewrite feat-b@: "(cat $log)
    exit 1
end
echo "ok: coordinator can rewrite feat-b@ directly"

echo "SMOKE-IMMUTABLE PASS"
