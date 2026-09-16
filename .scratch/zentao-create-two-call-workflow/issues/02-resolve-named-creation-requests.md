# 02: Resolve named creation requests in preflight

**What to build:** A caller can provide ordinary names such as the ZenTao service, project, module, and Chinese assignee, and the same preflight invocation either produces a fully resolved confirmation plan or a compact ambiguity response.

**Blocked by:** 01: One-call preflight for fully specified requests.

**Status:** resolved

- [x] Unique service, project, leaf-module, and assignee names resolve to their live identifiers within the preflight invocation.
- [x] Ambiguous or unavailable names return only relevant candidates and create nothing.
- [x] A normal named request no longer requires separate help, project-list, module-list, source-inspection, or ad hoc Python invocations.
- [x] Runnable checks cover one uniquely resolved request and one ambiguous request.

## Answer

The batch preflight now accepts either a numeric project ID or a project name, plus numeric or named modules and account or Chinese assignee names. It resolves against live project data, only matches named modules from the leaf set, and prefers exact identifiers or normalized names before related-name matches. A unique request produces the same compact confirmation plan as an ID-based request. Ambiguous or unavailable names return `needs_confirmation` JSON with only relevant candidates and exit before any create call. Offline CLI checks cover service routing, a fully resolved Chinese-name request, and an ambiguous module request with zero writes.
