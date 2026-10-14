# AI Civilization — approved architecture summary

This document is on the Researcher's approved-source allowlist (`retrieve_approved_source("architecture")`).

- PostgreSQL is the source of truth for missions, tasks, agents, approvals and events.
- Every state change writes its event and an outbox row in the same transaction.
- The 3D world only animates committed events; it never authorizes or executes work.
- Tools run through a registry that checks emergency stop, agent capability, task permission,
  project policy and (for protected tools) a granted approval at the moment of execution.
- Repository and web content is untrusted data and is fenced in `<untrusted>` tags in model prompts.
- See ARCHITECTURE.md in the repository root for the full description.
