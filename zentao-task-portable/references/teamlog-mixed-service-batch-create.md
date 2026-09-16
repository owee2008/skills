# Teamlog placeholders → mixed-service ZenTao batch creation

Use this reference when confirmed teamlog placeholders must become tasks across tycd and typm.

## Flow

1. Read the affected teamlog rows and build the final task drafts. Keep historical mappings as recommendations, never as live facts.
2. Group drafts by ZenTao service and project. The creation CLI has one service/project per request, so each group gets one request JSON.
3. For every group, run exactly one preflight:

```bash
python3 "$SKILL_DIR/scripts/zentao-create-task-refactored.py" --batch-json request.json --dry-run > approved-plan.json
```

4. Show one combined confirmation table. A preflight returning `needs_confirmation` contributes only its relevant candidates; update that request and rerun its preflight. Use only the relevant candidates returned by preflight; project/module discovery and create-page parsing stay inside that invocation.
5. After explicit authorization, execute each approved service/project plan once:

```bash
python3 "$SKILL_DIR/scripts/zentao-create-task-refactored.py" --approved-plan approved-plan.json
```

6. Each execution JSON supplies exact task IDs, verified fields, source (`created`/`reused`/`recovered`), and one screenshot path for its group. Only after every group verifies successfully, update the matching teamlog rows.

## Reporting

Return participant → task ID, service, project/module, assignee, estimate, dates, source, and one screenshot per executed group.
