---
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
   `${CLAUDE_PLUGIN_ROOT}/jjworkflow.example.toml` into the repo root as
   `jjworkflow.example.toml` and point the user at its keys: `workspace_dir`,
   `provision_hook`, `todo_cmd`.

4. Recommend adding `"env": {"JJ_EDITOR": "false"}` to the repo's
   `.claude/settings.json` — belt-and-braces so no jj command can hang waiting
   on an editor (the toolkit itself always passes `-m`).

5. If Claude Code background sessions (or `isolation: worktree` subagents) will
   run in this repo, wire EnterWorktree to jj-workflow workspaces by adding to
   the repo's `.claude/settings.json` `hooks` block:

   ```json
   "WorktreeCreate": [{"hooks": [{"type": "command", "command": "fish \"<HOOKS>/worktree_create.fish\""}]}],
   "WorktreeRemove": [{"hooks": [{"type": "command", "command": "fish \"<HOOKS>/worktree_remove.fish\""}]}]
   ```

   where `<HOOKS>` is `$CLAUDE_PROJECT_DIR/scripts/hooks` for a repo-local
   install, or the absolute `${CLAUDE_PLUGIN_ROOT}/scripts/hooks` path resolved
   NOW for a plugin install (plugin paths change on update — re-run this setup
   after updating the plugin). EnterWorktree then creates a real jj-workflow
   feature workspace — claiming the matching ticket when the worktree name
   names one (`claim --or-start`); the git-worktree logic is fully replaced.
   Removal maps to plain `workflow drop`: integrated or untouched ad-hoc
   workspaces are dropped (dir deleted), while one holding un-integrated work
   is refused and kept. Finish flow for such a workspace: commit, `workflow
   integrate NAME` from the coordinator (the workspace survives, parked on the
   integrated tip), then exit the worktree choosing "remove" to clean it up.
   These hooks are per-repo ON PURPOSE: registered globally they would hijack
   EnterWorktree in plain-git repos.

6. Sanity check: `workflow` with no arguments prints usage (the plugin's `bin/`
   is on PATH). The PreToolUse guard hook ships with this plugin and needs no
   registration.
