---
name: setup
description: Set up the jj-workflow toolkit in the current jj repo — configure the trunk-immutability guard and optional per-repo config. Use when the user asks to set up, install, initialize, or onboard jj-workflow in a repository.
---

# jj-workflow setup

Run these steps from the repo's **default (coordinator) workspace**. Each step
is idempotent; report what was already in place.

1. Confirm this is a jj repo: `jj workspace root`. If it fails, stop and say so.

2. Set the trunk-immutability alias (repo config; `@` resolves per-workspace, so
   this one alias locks the default line from every feature workspace while
   leaving the coordinator open):

   ```
   jj config set --repo 'revset-aliases."immutable_heads()"' 'builtin_immutable_heads() | (default@ ~ @)'
   ```

   Verify: `jj config list --repo` shows the alias. **This step is the actual
   protection** — without it, any feature workspace can rewrite shared trunk
   history with plain jj commands.

3. If the repo has no `jjworkflow.toml` and the user wants non-default behavior
   (workspace location, provision hook, ticket tool), copy
   `jjworkflow.example.toml` — it sits beside this SKILL.md — into the repo root
   and point the user at its keys: `workspace_dir`, `provision_hook`,
   `todo_cmd`.

   Feature workspaces default to `.workspaces/` inside the repo, which every
   host can write to. The toolkit keeps that directory invisible to jj on its
   own (a `.gitignore` holding `*` goes inside it), so there is no ignore step
   to perform here. `workspace_dir` overrides the base; `".."` gives the
   sibling layout.

4. Recommend setting `JJ_EDITOR=false` so no ad-hoc jj command can hang waiting
   on an editor (the toolkit itself always passes `-m`):

   - Codex: add `set = { JJ_EDITOR = "false" }` under
     `[shell_environment_policy]` in the trusted repo's `.codex/config.toml`.
     Merge with an existing `set` table instead of adding a duplicate.
   - Claude Code: add `"env": {"JJ_EDITOR": "false"}` to
     `.claude/settings.json`.

5. Claude Code only: if background sessions (or `isolation: worktree` subagents)
   will run in this repo, wire EnterWorktree to jj-workflow workspaces:

   ```json
   "WorktreeCreate": [{"hooks": [{"type": "command", "command": "fish \"<HOOKS>/worktree_create.fish\""}]}],
   "WorktreeRemove": [{"hooks": [{"type": "command", "command": "fish \"<HOOKS>/worktree_remove.fish\""}]}]
   ```

   `<HOOKS>` is the plugin's `hooks` directory as an ABSOLUTE path. No variable a project settings file can use points at the
   plugin root (`${CLAUDE_PLUGIN_ROOT}` is only set for hooks a plugin itself
   declares), which makes this machine-specific config: it MUST go in the
   untracked `.claude/settings.local.json`, never the tracked
   `.claude/settings.json`. A `/home/<user>/…` path in a version-controlled file
   breaks the hook for every other clone and leaks the author's home directory
   into history. Prefer `"$HOME/…"`, and prefer a stable checkout over the
   versioned plugin-cache path (`…/plugins/cache/<mp>/<plugin>/<version>/`),
   which moves on every plugin update and would need this step re-run.

   These hooks are per-repo ON PURPOSE: registered globally they would hijack
   EnterWorktree in plain-git repos. Codex has no equivalent event — skip this
   there and use `workflow start`/`claim` directly.

   EnterWorktree then creates a real jj-workflow feature workspace — claiming
   the matching ticket when the worktree name names one (`claim --or-start`);
   the git-worktree logic is fully replaced. Removal maps to plain `workflow
   drop`: integrated or untouched ad-hoc workspaces are dropped (dir deleted),
   while one holding un-integrated work is refused and kept. Finish flow:
   commit, `workflow integrate NAME` from the coordinator (the workspace
   survives, parked on the integrated tip), then exit the worktree choosing
   "remove" to clean it up. ExitWorktree's git-native pre-remove check can't
   read a jj workspace, so it refuses with "could not verify" — pass
   `discard_changes: true`; that only skips the bogus git gate, the non-force
   `workflow drop` in the hook is still the real gate (it keeps un-integrated
   work).

   The status line needs no step: it ships registered in the plugin's own
   `hooks.json` for `SessionStart` and `PostToolBatch`. Codex has neither
   event; there, run `workflow status` by hand when orientation is needed.

6. Sanity check: run `../jj-workflow/scripts/workflow` — relative to this
   skill's own directory — with no arguments; it prints usage. It is not on
   PATH and is not supposed to be, so that directory is the only place to look
   for it.

7. In Codex, remind the user to open `/hooks` once and trust this plugin's
   PreToolUse guard. Installing a plugin does not implicitly trust its
   executable hooks, and until it is trusted the git / bypass-flag ban is not
   enforced. This does not affect whether the commands run — only whether jj
   misuse is caught.
