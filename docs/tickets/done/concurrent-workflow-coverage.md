# Exercise multiple concurrent Kata workflows

The repository lock and workspace banking logic have only unit-level or mocked
coverage. Add real subprocess tests for the concurrency contracts demonstrated
by the 0.10.2 baseline and the 0.12.4 stress audit.

Acceptance criteria:

- Exercise same-name/same-item contention with one clean winner.
- Exercise lock waiting and timeout without partial state.
- Exercise concurrent lifecycle operations with dirty siblings.
- Assert no silent stale or divergent working-copy state remains.
- Keep stress-heavy loops outside the default test path.
