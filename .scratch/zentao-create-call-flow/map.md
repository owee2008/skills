# Reduce ZenTao creation to one preflight and one execution call

## Destination

A decision-complete optimization specification for the ZenTao task-creation flow: an agent reaches a safe confirmation draft with one preflight invocation, then creates and verifies the confirmed tasks with one execution invocation.

## Notes

- Scope: `/Users/zhou/vibecoding/skills/zentao-task-portable`, creation only.
- Evidence: `/Users/zhou/Downloads/01a0a9b2-cf11-73be-9891-2a70c74666d9.jsonl` contains 23 tool calls: 4 reads, 16 shell calls, 2 writes, and 1 edit. Repeated project/module discovery and dry-runs dominate the avoidable orchestration.
- The target is agent-level invocations, not a promise that each CLI invocation performs only one HTTP request.
- Preserve live project/module/assignee validation, explicit confirmation, exact-name idempotency, uncertain-write recovery, and detail read-back.
- Use `mattpocock-skills:grilling` and `mattpocock-skills:domain-modeling` for decision tickets.
- Planning only. Implementation starts after this map is cleared and converted into a specification.

## Decisions so far

## Not yet specified

- Whether internal ZenTao HTTP discovery should be consolidated after agent-level invocation count reaches the target. This depends on measuring the remaining latency after the CLI contract is settled.
- Which creation concepts deserve durable names in the Skill glossary after the preflight and confirmation boundaries are decided.

## Out of scope

- Query, edit, close, finish, effort-log, and project-migration flows.
- Implementing or deploying the optimized Skill while this map is open.
- Changing ZenTao server behavior, permissions, or data.
