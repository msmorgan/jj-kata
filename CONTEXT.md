# Kata Workspace Coordination

Kata coordinates feature work and ticket ownership across Jujutsu workspaces.

## Language

**Feature-local visibility**: A claim whose ticket transition exists only on
the owning feature line until integration. Its configuration value is
`feature`.
_Avoid_: Private visibility, non-shared mode

**Shared visibility**: A claim whose ticket transition is recorded in a
bookmarked anchor on the default line, making the claimed state visible to
later workspaces.
