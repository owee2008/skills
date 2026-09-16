# 04: Adopt the two-call workflow without breaking existing callers

**What to build:** Existing creation callers remain functional while Skill guidance and examples consistently use one preflight invocation followed by one execution invocation.

**Blocked by:** 01: One-call preflight for fully specified requests; 03: Execute an approved plan safely in one call.

**Status:** ready-for-agent

- [ ] Existing positional creation arguments and batch JSON inputs either retain their behavior or receive an explicit, tested migration path.
- [ ] Existing machine-readable result fields and screenshot behavior required by current callers remain available.
- [ ] Skill guidance no longer instructs agents to probe help, list projects, list modules, inspect source, or write ad hoc orchestration when the unified preflight covers the request.
- [ ] A representative named batch request demonstrates one preflight invocation before confirmation and one execution invocation after confirmation.
- [ ] All offline creation-flow checks pass, and no live ZenTao task is created without separate explicit authorization.
