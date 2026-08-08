---
name: handoff
description: Write or resume a HANDOFF.md — the note that hands an unfinished thread to the next session in a jj-workflow repo, whether that thread is code to finish, a question to work up, a call to make, work to check, or context worth keeping. Use when asked to create/write a handoff doc, hand something off, kick a discussion to another model, or pause with a resume note; and when asked to resume from handoff, pick up where a previous session left off, or whenever a HANDOFF.md turns up in a workspace.
---

# handoff

A `HANDOFF.md` hands an unfinished thread to the next session. **The existence of
the file means there is a follow-up** — that is its entire signalling job, so it
is never committed and never left behind after the thread is taken up.

**A follow-up is not always work to deliver.** It might be a question to work up,
a call for the user to make, a change to check, or context that would be
expensive to reconstruct and has nothing due yet. Every handoff therefore
declares a **Kind**, and the Kind says what the next session hands back:

| Kind | The next session hands back |
|---|---|
| `build` | a change |
| `discuss` | the question worked up — research, design, options on the table; nothing committed |
| `decide` | a pick among options already framed |
| `review` | a verdict on work already done |
| `park` | nothing; it is a save so the context isn't lost |

Getting this wrong is the most expensive mistake the doc can make. An agent
handed a `discuss` thread that is dressed as a `build` will start writing code to
answer a question nobody has settled; an agent handed a `park` dressed as
anything else will invent work.

It lives as uncommitted content in its workspace's working-copy commit (`@`).
That placement is deliberate: `jj st` and `jj diff --summary` then surface it on
every routine status check, so nobody has to remember to look.

Two halves below — **Writing a handoff**, and **Resuming from a handoff**. Read
the one you need.

Commands below are spelled `workflow`. It lives at
`../jj-workflow/scripts/workflow`, relative to this skill's own directory —
call it by that absolute path, from the workspace you mean.

## Writing a handoff

### 1. Refuse unless the working copy is empty

Run `jj st`. If `@` holds any changes, **stop and refuse** — do not write the
file. Tell the user to `jj commit -m …` (or abandon) the in-flight edits first,
then re-run.

This is not fussiness. A handoff points at *committed* state by change id; loose
edits in `@` are invisible to that description and easy for the next agent to
clobber. It also keeps `HANDOFF.md` the sole content of `@`, so deleting it on
resume returns the working copy to clean and empty.

**One exception:** if the only change in `@` is an existing `HANDOFF.md`, you are
updating a handoff already in place. Proceed and overwrite it.

### 2. Name the Kind before you write a word

Decide which of the five this thread is, by asking **what the next session hands
back** — not what it is about. Signs, in order of how often they are mistaken:

- **`build`** — the user set a multi-step goal you have not finished; there are
  commits on this feature stack; a plan or todo list is partly done; you were
  mid-way through chasing a failing test. There is a next command to run.
- **`discuss`** — a question came up that the conversation did not settle, and
  settling it means research or design rather than typing. The user wants it
  taken further — often by a *different* model or a fresh session. There may be
  no commits at all. **This is the kind most often mis-filed as `build`,** because
  the writer knows what they'd try first and writes that down as a "next step" —
  which quietly presumes the answer the next session was supposed to reach.
- **`decide`** — the options are already on the table with their tradeoffs, and
  what's missing is a commitment. If you cannot list the options, this is a
  `discuss`, not a `decide`.
- **`review`** — something is finished, or claims to be, and nobody has checked
  it. Broader than `/code-review`: "is this design sound", "did that migration
  actually land", "does the doc match the behaviour" are all `review`.
- **`park`** — the thread is real but nothing is due. Something was learned or
  decided that would be expensive to reconstruct, and it may become actionable
  later or never. A `park` is the one kind that must **not** carry a next step.

If two fit, pick the earlier-stage one — `discuss` over `decide`, `decide` over
`build`. Over-stating readiness is what makes an agent start typing too early.

### 3. Refuse unless there is genuinely a thread

**If there is no real follow-up of any kind, do nothing.** Do not write the file.
Tell the user there is nothing to hand off and ask what they wanted captured.

Never manufacture a thread out of repo state, a ticket backlog, or recent commits
that are already finished — a handoff describing something nobody is carrying is
worse than no handoff, because the next agent will act on it. Note that `park`
does **not** lower this bar: "nothing is due" is not "nothing happened". A `park`
still needs a real thread whose context you can state.

### 4. Write the doc, and do not commit it

Write `HANDOFF.md` at the root of the workspace you are in (`jj workspace root`).
Do **not** run `jj commit` or `jj describe` afterwards. jj auto-snapshots it into
`@` on the next command; that is exactly where it should stay.

Write for an agent with **zero** context — no memory of this conversation, no
idea what was tried. Prefer change ids, file paths, and exact commands over
prose. Use the common frame below plus **only** the body for your Kind. Skip any
section that has nothing real to say rather than padding it.

#### Common frame — every kind

```markdown
# HANDOFF

**This file's existence means there is a follow-up.** It is deliberately
uncommitted in `@`.

- **Kind:** `build` | `discuss` | `decide` | `review` | `park` — <one clause on
  what the next session hands back, in this thread's own terms>
- **Intended for:** who this is aimed at — a named model (`Fable`), the user, or
  `any agent`. Omit the line entirely if it genuinely doesn't matter.
- **Workspace:** `NAME` (`/abs/path/to/workspace`)
- **Written:** YYYY-MM-DD
- **Trunk at handoff:** `<change-id>` — <its description>

**This thread is not yours by default.** Finding this file is not permission to
act on it — it may belong to a different effort than the session that found it,
and the **Intended for** line above may name someone else. You may pick it up
only if one of these is true:

- the user told you to resume from a handoff, or
- you showed them the **Kind** and the heading below and they confirmed it is
  this session's to take.

Anything else — they say no, they say "later", you have no user to ask — means
leave this file exactly where it is, do not delete it, and carry on with what
you were already doing. If you do take it, delete this file first; see "Burn
after reading" at the bottom.
```

Then the body for the Kind, then the common tail. **Do not include sections from
a Kind that is not yours** — an unused "Next step" heading is exactly how a
`discuss` gets mistaken for a `build`.

#### Body — `build`

```markdown
## The task
What the user actually asked for, in their terms. One paragraph. Include the
"why" if it shapes the work.

## Where it stands
What is done and committed (change ids + one line each), and what is not.
Be honest about what is unverified — say "written but never run", not "done".

## Next step
The single concrete thing to do next. A command to run or a file to edit,
not "continue the implementation".
```

#### Body — `discuss`

```markdown
## The question
What is actually being asked, in the user's terms — the open question, not a
task. If you can only phrase it as "figure out X", say that; a vague question
honestly stated beats a sharp one you invented.

## Why it is open
What made this a question rather than a decision: what the conversation hit,
what the constraint is, why the obvious answer doesn't work.

## Already ruled out
Options considered and dropped, each with the reason. **The highest-value
section in this kind** — without it the next session re-walks your dead ends.

## Options so far
Whatever is on the table, with what is unresolved about each. May be empty —
producing this list is the job being handed over, not a prerequisite.

## What is waiting on this
What cannot proceed until the question is settled, if anything.
```

**No "Next step" section in a `discuss`.** Whatever you would write there is your
guess at the answer, and the next session will read it as the plan.

#### Body — `decide`

```markdown
## The decision
The call to make, stated as a question with a finite answer set.

## The options
Each one, with its tradeoff. Required — if you cannot fill this in, the Kind is
`discuss`, not `decide`. Say which way you lean and why, marked as a lean.

## Who decides
The user, a named model, or whoever picks this up. Say if it is not the reader.

## What is blocked on it
What cannot proceed until the call is made.
```

#### Body — `review`

```markdown
## What to check
The change ids, paths, or behaviour under review, and where they live.

## Against what
The standard it has to meet — a ticket's acceptance criteria, a spec, "it
actually runs", a design it is supposed to implement. A review with no stated
standard turns into an opinion.

## Already checked
What has been verified and how, so the reviewer doesn't redo it. Be honest
about what was assumed rather than run.
```

#### Body — `park`

```markdown
## What this is
The thread, and why it is worth keeping — what would be expensive or impossible
to reconstruct from the repo alone.

## Nothing is due
State it plainly: no action is expected of the next session. Do not invent one.

## What would make this live
The trigger, if there is one — a release, a dependency landing, a decision
elsewhere. "Nothing known" is a fine answer.
```

#### Common tail — every kind

```markdown
## Decisions already made — do not re-litigate
Choices the user made or approved, with the reason. This is the section that
saves the most time: without it the next session re-opens settled questions.

## Gotchas
Dead ends already tried, surprising behaviour, things that look wrong but are
correct. Anything that cost you time and would cost it again.

## Key files
Paths worth reading first, each with a clause on why.

## Open questions for the user
Things genuinely blocked on a human answer. Empty is a fine answer.

## Burn after reading
Once this thread is yours by the test at the top of this file, delete it
(`rm HANDOFF.md`) **before** doing anything else. It has served its purpose;
leaving it risks committing it and misleads whoever comes next. If the thread is
not yours, leave the file untouched.

**Exception for `park`:** reading a park is not taking it. Leave the file in
place unless you are converting it into real work, or the user says it is no
longer worth keeping.
```

### 5. Report

Tell the user the path, the workspace, **the Kind and who it is intended for**,
and a one-line summary of what was captured. Remind them the file is uncommitted,
that its presence is the signal that a thread is open here, and that the next
session can be pointed at it with "resume from handoff" (or will find it via
`workflow handoffs`, which prints each hit's Kind).

## Resuming from a handoff

### 1. Find it

Run `workflow handoffs` — a read-only scan of every workspace in the repo,
printing `NAME<TAB>PATH` per hit on stdout and a summary naming each hit's Kind
on stderr. Status is grep-style: **0** = at least one found, **1** = none. It is
safe from any workspace.

- **In the workspace that has one** → that is your candidate.
- **In `default` with no `HANDOFF.md` there, but hits elsewhere** → you will be
  resuming *from inside* that workspace; `cd` there, and it is yours for the rest
  of the session. **Confirm with the user which one to take — always, even when
  there is exactly one hit.** Picking a workspace silently commits the session to
  someone else's open thread.
- **No hits at all** → say so. Do not go looking for work to do instead.

### 2. Establish that the thread is yours

A handoff is **not yours by default.** It records what *someone else's* session
was carrying; this session may have been started for something unrelated, and
silently adopting a stranger's open thread is worse than ignoring it. Finding the
file is not permission. Exactly two things grant it:

1. **The user already told you to resume from a handoff.** Then resume
   immediately — no confirmation step, no summarising the doc back at them
   first. They asked for this.
2. **You asked and they confirmed.** Show them the doc's **Kind**, its
   **Intended for** line, and its heading question or task, plus the workspace it
   is in, and ask whether it is theirs to take this session. One question, with
   the specifics in it — not "I found a handoff, should I read it?"

Nothing else counts. In particular: the doc looking related to the current
conversation, being the only handoff in the repo, or the session having no other
work to do are **not** grants — the first two are guesses about intent, the
third is a reason to ask the user what they want, not to invent a task.

**An `Intended for` naming someone other than you is a reason to ask, not a
reason to take it.** If it says `Fable` and you are not Fable, say so when you
ask; the user may have been waiting to route it.

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

Once you have decided to take the thread, `rm HANDOFF.md` **first**, before any
other work. Three reasons: a stale doc misleads the next agent, an undeleted one
gets committed by accident, and removing it returns `@` to clean and empty so you
start from the same footing the writer had. Its contents are already in your
context — you do not need the file on disk.

**A `park` is the exception**: reading it is not taking it, and there is nothing
to finish, so leave it in place. Delete it only when you convert it into real
work — at which point write the replacement handoff, or just do the work — or
when the user says it is no longer worth keeping.

### 5. Then act on the Kind

Re-read the files and changes the doc points at. A handoff is a set of pointers
and a record of decisions, not a replacement for reading the code. Then:

- **`build`** — pick up at "Next step".
- **`discuss`** — the deliverable is the question worked up, **not a change**. Do
  not start editing code to answer it. Read "Already ruled out" before proposing
  anything, and come back to the user with options and tradeoffs. If you end up
  convinced of one answer, say so as a recommendation and let them take it.
- **`decide`** — if "Who decides" is the user, put the options to them and stop;
  do not decide on their behalf because it seems obvious. If it is you, make the
  call, say why, and record it before acting on it.
- **`review`** — check against the stated standard and report a verdict, not a
  fix. Do not silently repair what you find unless the user asks; a review that
  turns into a rewrite loses the finding.
- **`park`** — there is nothing to do. Say what the park holds and ask whether
  they want it picked up now. Do not start work on it.
