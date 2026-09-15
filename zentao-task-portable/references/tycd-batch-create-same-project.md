# 田一禅道同项目同负责人批量创建任务

Use this reference when Zhou asks to create several new tasks in the same田一禅道 project/module/assignee, especially after giving a compact list of task titles and a shared estimate.

## Proven flow

1. Resolve service/project/module/assignee before creating:
   - 田一禅道: `https://tycd.tygps.com`
   - 口语「我的日志项目」通常 resolves to project `1681` / 「我的日志」.
   - 口语「PC版本模块」 in this project maps to realtime module `/APP/Web 我的日志` (`9721`) after querying modules.
   - Verify Chinese assignee on `/biz/task-create-<projectID>.html`; extract `<option value>` from the `assignedTo[]` select. Example seen: 张旭男 = `zhangxunan`.
2. Recalculate default dates at execution time, not just preview time:
   - `begin = today - 5 days`
   - `end = today + 10 days`
3. Show the final create table in normal chat and wait for an explicit confirmation before writing. If only hours were missing, accept a later reply such as “每个任务10小时” as filling the draft, then re-show final table and wait for “确认/确认创建”.
4. Create in one Python process, reusing one `ZentaoClient('https://tycd.tygps.com')` login session. For each task:
   - `verify_task_created(project_id, name)` before POST to avoid duplicates.
   - `create_task(project_id, name, module=..., assigned_to=..., task_type='devel', estimate=..., begin=..., end=..., desc=...)`.
   - If `create_task` response only locates the project task list and has no task id, call `verify_task_created(project_id, name)` to recover the id.
   - `get_task_detail(task_id)` and verify `project`, `module`, `assignedTo`, `type`, `estimate`, `left`, `estStarted`, `deadline`, `status`, and `name`.
5. Generate one screenshot for the last/newest task using:

```bash
python3 "$SKILL_DIR/scripts/zentao-screenshot-task.py" <lastTaskID> 'tycd 田一禅道' <projectID>
```

## Minimal script shape

```python
from scripts.zentao_common import ZentaoClient

client = ZentaoClient('https://tycd.tygps.com')
client.login_with_available_credentials()

for name in task_names:
    existing = client.verify_task_created(project_id, name)
    if existing:
        task_id = existing['id']
    else:
        created = client.create_task(
            project_id,
            name,
            module=module_id,
            assigned_to=assignee,
            task_type='devel',
            estimate=estimate,
            begin=begin,
            end=end,
            desc=f'按用户要求创建：{name}',
        )
        task_id = created.get('id') or client.verify_task_created(project_id, name)['id']
    detail = client.get_task_detail(int(task_id))
    # verify fields from detail/raw_fields before reporting success
```

## Reporting

Return a compact table with task id, task name, project, module, assignee, type, estimate, left, begin, deadline, and status. Include the screenshot as `MEDIA:<path>`.
