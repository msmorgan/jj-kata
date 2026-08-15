---
needs:
  - kanban-origin-rollback
  - baseline-parity-coverage
  - concurrent-workflow-coverage
  - self-hosted-test-isolation
---

# Release jj-kata 0.12.5

Publish the audited ownership fix and durable baseline/concurrency coverage,
then refresh the installed Codex plugin from the released marketplace entry.

Acceptance criteria:

- Bump every package and host manifest to 0.12.5.
- Run the complete test and lint suite after integration.
- Push the release through Jujutsu.
- Verify Codex reports jj-kata 0.12.5 installed and enabled.
