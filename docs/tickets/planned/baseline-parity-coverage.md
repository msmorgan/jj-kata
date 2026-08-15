# Preserve Kata-owned jj-workflow 0.10.2 lifecycle properties

Port the high-value sequential smoke properties that remain Kata's
responsibility after the Python rewrite. Do not duplicate behavior now owned by
jj-sensei or Baton, and do not restore intentionally retired bulk-drop or guard
features.

Acceptance criteria:

- Cover merge-default and cross-feature refusals.
- Cover bounded force-drop around a foreign descendant.
- Cover dirty sibling banking and feature-side claim accretion.
- Cover supported workspace directory and worktree-hook variants.
- Keep the suite focused on observable lifecycle properties.
