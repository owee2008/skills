# 03: Execute an approved plan safely in one call

**What to build:** After the user approves the preflight plan, one execution invocation creates or safely reuses every task, recovers uncertain writes, verifies the saved fields, and returns one compact result.

**Blocked by:** 02: Resolve named creation requests in preflight.

**Status:** resolved

- [x] One execution invocation accepts the approved plan and revalidates every fact that may have become stale before writing.
- [x] Exact-name lookup never reuses a merely similar historical task.
- [x] A timed-out or interrupted create is queried before any retry, preventing duplicate tasks.
- [x] The result reads back project, module, assignee, type, estimate, left, start date, and deadline for every task, and generates at most one screenshot for the batch.
- [x] Runnable checks cover newly created, exactly reused, uncertain-write recovered, and verification-failed outcomes without writing to a live service unless separately authorized.

## Answer

Preflight output is now a versioned approved-plan contract (`dry_run=true`, `status=ready`, `plan_version=1`) consumed through `--approved-plan`. Execution revalidates the approved numeric project ID, numeric module IDs, and exact assignee accounts before writing; stale facts require a fresh preflight and are never fuzzy-remapped. Exact-name lookup handles reuse, while only `ZentaoWriteOutcomeUnknown` triggers a post-write exact lookup and `recovered` result. Definite validation failures are re-raised. Every successful task is read back for project, module, assignee, type, estimate, left, start date, and deadline, and a successful batch takes one screenshot. Offline CLI checks cover created, reused, recovered, malformed plan, stale facts, definite failure, and read-back mismatch outcomes.
