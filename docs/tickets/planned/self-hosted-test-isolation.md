# Isolate tests from the checkout's Kata configuration

The Kanban subprocess helper inherits the repository working directory. Once
jj-kata manages itself through `kata.toml`, tests that pass an external
`--root` accidentally inherit this repository's configured column order.

Acceptance criteria:

- Run temporary-board subprocesses from their temporary project context.
- Keep explicit config-discovery tests unchanged and meaningful.
- Run the full suite from this self-managed checkout without configuration
  leakage.
- Investigate and eliminate any test-created shared jj configuration race.
