# 04: Adopt the two-call workflow without breaking existing callers

**What to build:** Existing creation callers remain functional while Skill guidance and examples consistently use one preflight invocation followed by one execution invocation.

**Blocked by:** 01: One-call preflight for fully specified requests; 03: Execute an approved plan safely in one call.

**Status:** resolved

- [x] Existing positional creation arguments and batch JSON inputs either retain their behavior or receive an explicit, tested migration path.
- [x] Existing machine-readable result fields and screenshot behavior required by current callers remain available.
- [x] Skill guidance no longer instructs agents to probe help, list projects, list modules, inspect source, or write ad hoc orchestration when the unified preflight covers the request.
- [x] A representative named batch request demonstrates one preflight invocation before confirmation and one execution invocation after confirmation.
- [x] All offline creation-flow checks pass, and no live ZenTao task is created without separate explicit authorization.

## Answer

Legacy positional arguments and direct batch JSON execution remain covered by public CLI checks. The preferred workflow is now documented consistently across the Skill entrypoint, creation guide, same-project batch reference, mixed-service teamlog reference, and real-module selection reference: one named request preflight saved as a versioned approved plan, explicit user confirmation, then one `--approved-plan` execution. The guidance treats preflight as the sole source of live project/module/assignee facts and removes help probes, separate list calls, source inspection, create-page parsing, and ad hoc Python from the normal creation path. A representative Chinese-name request is tested through exactly one preflight and one approved execution, with preserved machine-readable task fields and one screenshot.
