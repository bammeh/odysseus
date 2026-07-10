# ADR 0001: Agent Orchestration Foundations

## Status

Accepted for the first implementation slice.

## Decision

Odysseus will model orchestration with explicit owner, agent, workspace,
namespace, and run identities. Alice, Bob, and Charlie are seeded default agent
profiles, not hard-coded limits. Users can create custom profiles and teams,
but safety policy remains system-owned.

Shell access is not the sandbox. File and code navigation tools must be bound
to a selected workspace or owner-scoped mount policy. Mounts reject broad host
roots, sensitive paths, symlink escapes, over-limit files, and disallowed file
extensions. Write-capable mounts require backup-before-overwrite policy.

Context passed into orchestration is represented as capsules with diagnostics.
Tool results used as evidence carry a truth contract: tool name, bounded excerpt,
output hash, timestamp, workspace or mount identity, and truncation status.

## Consequences

- The first backend slice is additive: new services and route modules rather
  than broad rewrites of `core/database.py`, `src/agent_loop.py`, or existing
  route layout.
- SQLite/file-backed storage is the v1 persistence layer; repositories and
  small store classes keep future Postgres/pgvector migration possible.
- Custom agents can specialize behavior, but they cannot weaken mount policy,
  tool policy, quality gate semantics, or owner isolation.
