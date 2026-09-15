# ZenTao Effort Log Batch Operations Notes

Session-derived implementation details for safely adding or deleting many effort rows on an existing task.

## Batch add effort rows

- Endpoint: `/biz/effort-createForObject-task-<task_id>.html?onlybody=yes`.
- GET the form first and preserve any non-row hidden fields.
- Row fields:
  - `id[n]`: row number as string
  - `dates[n]`: `YYYY-MM-DD`
  - `consumed[n]`: hours, e.g. `1.5`
  - `left[n]`: remaining hours for the task after that row
  - `objectType[n]`: `task`
  - `objectID[n]`: task ID
  - `work[n]`: work description
- This instance reliably accepted the visible 3-row batch form; for larger ranges, submit in batches of 3 and refresh the form each batch.
- Modal-close HTML with HTTP 200 can mean success. Always verify by querying `zt_effort` and then `zt_task`.

## Delete all effort rows under one task

1. Query and save a backup before deleting:
   - task: `select id,name,project,module,assignedTo,status,estimate,consumed,\`left\`,deadline,estStarted from zt_task where id=<task_id> limit 1`
   - efforts: `select id,date,account,consumed,\`left\`,work,project,objectID,objectType from zt_effort where objectType='task' and objectID=<task_id> order by id asc`
2. For each effort ID, call the official delete-confirm endpoint while logged in:
   - `/biz/effort-delete-<effort_id>-yes.html`
3. Verify each ID is gone with `select id from zt_effort where id=<effort_id> limit 1`.
4. Final verification:
   - `zt_effort` for the task has zero rows.
   - `zt_task` is re-read; ZenTao recalculates `consumed` and `left`, so report those actual values.

## Delete one effort row by effort ID

Use the same safety model for a single explicit effort/log ID, but keep the flow concise when the user clearly names exactly one ID.

1. Treat the supplied ID as `zt_effort.id`; query it before writing, preferably joined to `zt_task` and `zt_user`, e.g. `zt_effort e left join zt_user u on u.account=e.account left join zt_task t on t.id=e.objectID`.
2. Save a JSON backup under `$WORKSPACE_DIR/zentao-change-backups/` containing the target row, the affected task row, and all effort rows for that task.
3. Delete via the official endpoint `/biz/effort-delete-<effort_id>-yes.html`; a modal-reload HTML response can be normal.
4. Verify with `select id from zt_effort where id=<effort_id> limit 1` and re-read the affected `zt_task` row. Report the actual before/after `consumed`, `left`, status, and effort-count changes.
5. Follow-up shorthand after deletion such as “剩余工时加 4 小时” normally refers to the just-affected task. Reuse that task ID, read the current task left first, set `left = current_left + N` through the normal task edit flow (e.g. `zentao-edit-task.py --user-text tycd <task_id> --left <new_left> --yes`), then read back the task to verify. Do not guess from the deleted effort row's `left`; ZenTao may recalculate `consumed` and leave `left` unchanged after deletion.

## Pitfalls

- Do not delete via direct SQL; use ZenTao form endpoints so task totals and lifecycle bookkeeping are updated by ZenTao.
- Do not rely on date/work snippets in the task view for verification; the task view may omit or collapse dates. SQL/API verification is clearer.
- A transient login failure that succeeds on retry is not a durable tool failure. Use retry for login and form submission before escalating.
