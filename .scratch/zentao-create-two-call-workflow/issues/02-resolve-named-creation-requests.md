# 02: Resolve named creation requests in preflight

**What to build:** A caller can provide ordinary names such as the ZenTao service, project, module, and Chinese assignee, and the same preflight invocation either produces a fully resolved confirmation plan or a compact ambiguity response.

**Blocked by:** 01: One-call preflight for fully specified requests.

**Status:** ready-for-agent

- [ ] Unique service, project, leaf-module, and assignee names resolve to their live identifiers within the preflight invocation.
- [ ] Ambiguous or unavailable names return only relevant candidates and create nothing.
- [ ] A normal named request no longer requires separate help, project-list, module-list, source-inspection, or ad hoc Python invocations.
- [ ] Runnable checks cover one uniquely resolved request and one ambiguous request.
