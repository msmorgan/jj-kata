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
   `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/jjworkflow.example.toml` into the repo
   root as `jjworkflow.example.toml` and point the user at its keys:
   `workspace_dir`, `provision_hook`, `todo_cmd`. Codex sets `PLUGIN_ROOT`;
   Claude Code sets `CLAUDE_PLUGIN_ROOT`.

   The workspace-location default is host-aware: the Codex plugin uses
   `.codex/workspaces` so feature workspaces stay inside the sandbox's writable
   repo root; other installs use sibling directories (`..`). An explicit
   `workspace_dir` overrides either default. Any in-repo workspace directory
   must be ignored; if `.codex/*` is not already covered by a global excludes
   file, add `.codex/workspaces/` to the repo's `.gitignore`.

4. Recommend setting `JJ_EDITOR=false` so no ad-hoc jj command can hang waiting
   on an editor (the toolkit itself always passes `-m`):

   - Codex: add `set = { JJ_EDITOR = "false" }` under
     `[shell_environment_policy]` in the trusted repo's `.codex/config.toml`.
     Merge with an existing `set` table instead of adding a duplicate.
   - Claude Code: add `"env": {"JJ_EDITOR": "false"}` to
     `.claude/settings.json`.

5. Claude Code, repo-local installs only: register the status line so an agent
   gets one line of "where am I" when a session starts and after each batch of
   tool calls. Add to `.claude/settings.json` (tracked — the path is portable):

   ```json
   "SessionStart":  [{"hooks": [{"type": "command", "command": "fish \"$CLAUDE_PROJECT_DIR/scripts/hooks/jj_status.fish\""}]}],
   "PostToolBatch": [{"hooks": [{"type": "command", "command": "fish \"$CLAUDE_PROJECT_DIR/scripts/hooks/jj_status.fish\""}]}]
   ```

   Both events, same script — it branches on `hook_event_name`. Neither takes a
   matcher. **Plugin installs already have this** — it ships in the plugin's own
   `hooks.json`, so skip this step there. Unlike the worktree hooks in the next
   step, registering it globally is safe: outside a jj repo it exits silently
   without invoking jj at all. Codex has neither event; there, run
   `workflow status` by hand when orientation is needed.

6. Claude Code only: if background sessions (or `isolation: worktree` subagents) will
   run in this repo, wire EnterWorktree to jj-workflow workspaces by adding a
   `hooks` block (see below for WHICH settings file):

   ```json
   "WorktreeCreate": [{"hooks": [{"type": "command", "command": "fish \"<HOOKS>/worktree_create.fish\""}]}],
   "WorktreeRemove": [{"hooks": [{"type": "command", "command": "fish \"<HOOKS>/worktree_remove.fish\""}]}]
   ```

   `<HOOKS>` and the settings file go together, because only a repo-local
   install has a path every contributor resolves the same way:

   - **Repo-local install** — `<HOOKS>` is `$CLAUDE_PROJECT_DIR/scripts/hooks`
     (`install.fish` flattens the toolkit into the target repo's `scripts/`).
     Portable, so it belongs in the tracked `.claude/settings.json`.
   - **Plugin install** — inside the plugin the scripts ship beside the skill
     that documents them, so the tail of the path is
     `skills/jj-workflow/scripts/hooks`. The toolkit lives outside the repo, and no variable
     usable in a project settings file points at it (`${CLAUDE_PLUGIN_ROOT}` is
     only set for hooks a plugin itself declares). So `<HOOKS>` must be an
     absolute machine path — which makes it machine-specific config that MUST
     go in the untracked `.claude/settings.local.json`, never in the tracked
     `.claude/settings.json`. Writing a `/home/<user>/…` path into a
     version-controlled file breaks the hook for every other clone and leaks
     the author's home directory into history. Prefer `"$HOME/…"` over a
     literal home path even there, and prefer a stable checkout over the
     versioned plugin cache path (`…/plugins/cache/<mp>/<plugin>/<version>/`),
     which moves on every plugin update and would need re-running this setup.

   Codex has no equivalent EnterWorktree hook, so
   skip this step there and use `workflow start`/`claim` directly.
   EnterWorktree then creates a real jj-workflow
   feature workspace — claiming the matching ticket when the worktree name
   names one (`claim --or-start`); the git-worktree logic is fully replaced.
   Removal maps to plain `workflow drop`: integrated or untouched ad-hoc
   workspaces are dropped (dir deleted), while one holding un-integrated work
   is refused and kept. Finish flow for such a workspace: commit, `workflow
   integrate NAME` from the coordinator (the workspace survives, parked on the
   integrated tip), then exit the worktree choosing "remove" to clean it up.
   ExitWorktree's git-native pre-remove check can't read a jj workspace, so it
   refuses with "could not verify" — pass `discard_changes: true`; that only
   skips the bogus git gate, the non-force `workflow drop` in the hook is still
   the real gate (it keeps un-integrated work). These hooks are per-repo ON
   PURPOSE: registered globally they would hijack EnterWorktree in plain-git
   repos.

7. Sanity check: `workflow` with no arguments prints usage (the plugin's
   PreToolUse hook prepends its `bin/` to each Codex shell call). The hook ships
   with this plugin and needs no registration. In Codex, if `workflow` is not
   found, stop and ask the user to use `/hooks` to review and trust the pending
   plugin hook; plugin installation does not implicitly trust executable hooks.
