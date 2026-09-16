# 03: Execute an approved plan safely in one call

**What to build:** After the user approves the preflight plan, one execution invocation creates or safely reuses every task, recovers uncertain writes, verifies the saved fields, and returns one compact result.

**Blocked by:** 02: Resolve named creation requests in preflight.

**Status:** ready-for-agent

- [ ] One execution invocation accepts the approved plan and revalidates every fact that may have become stale before writing.
- [ ] Exact-name lookup never reuses a merely similar historical task.
- [ ] A timed-out or interrupted create is queried before any retry, preventing duplicate tasks.
- [ ] The result reads back project, module, assignee, type, estimate, left, start date, and deadline for every task, and generates at most one screenshot for the batch.
- [ ] Runnable checks cover newly created, exactly reused, uncertain-write recovered, and verification-failed outcomes without writing to a live service unless separately authorized.
