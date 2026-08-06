---
name: handoff
description: Write or resume a HANDOFF.md — the mid-flight save that lets a fresh agent pick up paused work in a jj-workflow repo. Use when asked to create/write a handoff doc, hand work off, or pause with a resume note; and when asked to resume from handoff, pick up where a previous session left off, or whenever a HANDOFF.md turns up in a workspace.
---

# handoff

A `HANDOFF.md` is a mid-flight save for an unfinished task. **The existence of
the file means there is work to resume** — that is its entire signalling job, so
it is never committed and never left behind after a resume.

It lives as uncommitted content in its workspace's working-copy commit (`@`).
That placement is deliberate: `jj st` and `jj diff --summary` then surface it on
every routine status check, so nobody has to remember to look.

Two halves below — **Writing a handoff**, and **Resuming from a handoff**. Read
the one you need.

Commands below are spelled `workflow`; run it by absolute path out of the
/jj-workflow:jj-workflow skill's own directory (`<skill dir>/scripts/workflow`).

## Writing a handoff

### 1. Refuse unless the working copy is empty

Run `jj st`. If `@` holds any changes, **stop and refuse** — do not write the
file. Tell the user to `jj commit -m …` (or abandon) the in-flight edits first,
then re-run.

This is not fussiness. A handoff describes *committed* state and points at
changes by change id; loose edits in `@` are invisible to that description and
easy for the next agent to clobber. It also keeps `HANDOFF.md` the sole content
of `@`, so deleting it on resume returns the working copy to clean and empty.

**One exception:** if the only change in `@` is an existing `HANDOFF.md`, you are
updating a handoff already in place. Proceed and overwrite it.

### 2. Refuse unless there is genuinely work in flight

Ask yourself what a new agent would need in order to continue *a task that is
actually underway*. Signs there is one: the user set a multi-step goal you have
not finished; there are commits on this feature stack; a plan or todo list is
partly done; you were mid-way through chasing a failing test.

**If there is no clear in-progress task or effort, do nothing.** Do not write the
file. Tell the user there is nothing to put in a handoff doc and ask what they
wanted captured. Never manufacture a task out of repo state, a ticket backlog, or
recent commits that are already finished — a handoff describing work nobody is
doing is worse than no handoff, because the next agent will act on it.

### 3. Write the doc, and do not commit it

Write `HANDOFF.md` at the root of the workspace you are in (`jj workspace root`).
Do **not** run `jj commit` or `jj describe` afterwards. jj auto-snapshots it into
`@` on the next command; that is exactly where it should stay.

Write for an agent with **zero** context — no memory of this conversation, no
idea what was tried. Prefer change ids, file paths, and exact commands over
prose. Skip any section that has nothing real to say rather than padding it.

```markdown
# HANDOFF

**This file's existence means there is work to resume.** It is deliberately
uncommitted in `@`.

**This work is not yours by default.** Finding this file is not permission to
act on it — it may belong to a different effort than the session that found it.
You may pick it up only if one of these is true:

- the user told you to resume from a handoff, or
- you showed them the **Task** line below and they confirmed it is this
  session's work.

Anything else — they say no, they say "later", you have no user to ask — means
leave this file exactly where it is, do not delete it, and carry on with what
you were already doing. If you do pick it up, delete this file first; see "Burn
after reading" at the bottom.

- **Workspace:** `NAME` (`/abs/path/to/workspace`)
- **Written:** YYYY-MM-DD
- **Trunk at handoff:** `<change-id>` — <its description>

## The task
What the user actually asked for, in their terms. One paragraph. Include the
"why" if it shapes the work.

## Where it stands
What is done and committed (change ids + one line each), and what is not.
Be honest about what is unverified — say "written but never run", not "done".

## Next step
The single concrete thing to do next. A command to run or a file to edit,
not "continue the implementation".

## Decisions already made — do not re-litigate
Choices the user made or approved, with the reason. This is the section that
saves the most time: without it the next agent re-opens settled questions.

## Gotchas
Dead ends already tried, surprising behaviour, things that look wrong but are
correct. Anything that cost you time and would cost it again.

## Key files
Paths worth reading first, each with a clause on why.

## Open questions for the user
Things genuinely blocked on a human answer. Empty is a fine answer.

## Burn after reading
Once the work is yours by the test at the top of this file, delete it
(`rm HANDOFF.md`) **before** doing anything else. It has served its purpose;
leaving it risks committing it and misleads whoever comes next. If the work is
not yours, leave the file untouched.
```

### 4. Report

Tell the user the path, the workspace, and a one-line summary of what was
captured. Remind them the file is uncommitted, that its presence is the signal
that work is paused here, and that the next session can be pointed at it with
"resume from handoff" (or will find it via `workflow handoffs`).

## Resuming from a handoff

### 1. Find it

Run `workflow handoffs` — a read-only scan of every workspace in the repo,
printing `NAME<TAB>PATH` per hit. Status is grep-style: **0** = at least one
found, **1** = none. It is safe from any workspace.

- **In the workspace that has one** → that is your candidate.
- **In `default` with no `HANDOFF.md` there, but hits elsewhere** → you will be
  resuming *from inside* that workspace; `cd` there, and it is yours for the rest
  of the session. **Confirm with the user which one to take — always, even when
  there is exactly one hit.** Picking a workspace silently commits the session to
  someone else's unfinished work.
- **No hits at all** → say so. Do not go looking for work to do instead.

### 2. Establish that the work is yours

A handoff is **not yours by default.** It records what *someone else's* session
was doing; this session may have been started for something unrelated, and
silently adopting a stranger's half-finished task is worse than ignoring it.
Finding the file is not permission. Exactly two things grant it:

1. **The user already told you to resume from a handoff.** Then resume
   immediately — no confirmation step, no summarising the doc back at them
   first. They asked for this.
2. **You asked and they confirmed.** Show them the doc's *Task* line and the
   workspace it is in, and ask whether it is theirs to deal with this session.
   One question, with the specifics in it — not "I found a handoff, should I
   read it?"

Nothing else counts. In particular: the doc looking related to the current
conversation, being the only handoff in the repo, or the session having no other
work to do are **not** grants — the first two are guesses about intent, the
third is a reason to ask the user what they want, not to invent a task.

If they decline, or the answer is "not now", or there is no user to ask (an
unattended run), leave the file exactly where it is — **do not delete it** — and
carry on with what you came for. An unclaimed handoff is harmless; a burned one
is unrecoverable.

### 3. Check it is still uncommitted

`jj st` should show `HANDOFF.md` as an added file in `@`. If the file exists on
disk but does not appear in `@`'s changes, **it was committed at some point after
the handoff was written**. Flag this to the user: the doc is now sitting in the
repo's history, the working copy has moved on since the handoff, and the doc may
describe a state that no longer holds. Sort that out before trusting its
contents.

### 4. Burn after reading

Once you have decided to resume, `rm HANDOFF.md` **first**, before any other
work. Three reasons: a stale doc misleads the next agent, an undeleted one gets
committed by accident, and removing it returns `@` to clean and empty so you
start from the same footing the writer had. Its contents are already in your
context — you do not need the file on disk.

### 5. Then actually resume

Re-read the files and changes the doc points at. A handoff is a set of pointers
and a record of decisions, not a replacement for reading the code. Pick up at
"Next step".
