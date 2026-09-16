# 01: One-call preflight for fully specified requests

**What to build:** A caller with explicit service, project, module, assignee, hours, and task names receives a compact confirmation plan from one preflight invocation, with live validation and no ZenTao writes.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] One preflight invocation validates the project state, module membership, assignee availability, task fields, and default dates for one or many tasks.
- [x] Preflight performs no create or update request and fails closed when required live validation is unavailable.
- [x] The confirmation output contains the exact fields needed for user approval without printing the complete project or module catalog.
- [x] A runnable offline check proves zero-write behavior and the compact success output.

## Answer

The existing batch JSON CLI remains the public seam. One `--dry-run` invocation now logs in once, validates the live project, selected module, available assignee, normalized task fields, and execution-time default dates, then returns only the selected confirmation data with human-readable module and assignee names. It does not expose the full leaf-module catalog and fails closed when live module or assignee options are unavailable. Offline CLI tests prove compact success, default dates, zero writes, and unavailable-assignee failure.
