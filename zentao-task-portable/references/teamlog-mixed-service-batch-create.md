# Teamlog placeholders → mixed-service ZenTao batch creation

Use this reference when a local `teamlog` matter has placeholder participant rows (`待确认` project/module/service, `待创建` task ID) and Zhou then says `创建禅道`, especially when the batch spans both 田一禅道 (`tycd`) and 天远/科技禅道 (`typm`).

## Proven flow

1. Read the affected `teamlog` matter and extract participant IDs, names, task names, and any hours from the latest progress note.
2. Build a recommended creation table from realtime module lists plus historical teamlog patterns:
   - Backend/OAuth/JWT environment tasks often fit typm `我的日志2026` `/运维和bug/我的日志环境` (`2699`) when Zhou confirms that module.
   - Android tasks: typm `我的日志2026` `/运维和bug/我的日志Android` (`2702`).
   - iOS tasks: tycd `我的日志` `/APP/IOS 我的日志` (`9649`) unless Zhou says otherwise.
   - 小程序 tasks: typm `我的日志2026` `/运维和bug/我的日志小程序` (`2701`) when working under the typm client-side track.
3. Before creating, realtime-query the full module lists for every target project. Recommend leaf modules, but do not write confirmed project/module fields to teamlog until Zhou confirms.
4. If Zhou replies with a small adjustment such as `qsx721 也用模块 2699，其他已确认`, treat it as both module confirmation and creation authorization **only if** the previous ordinary chat message showed the full creation table with service, project, module, assignee, task name, hours, and dates.
5. Verify assignees on each target project’s `/biz/task-create-<projectID>.html` page by parsing `assignedTo[]` options. Do not rely only on pinyin guesses. Accounts verified in this workflow:
   - typm project `428`: 周丙龙=`zhoubinglong`, 李东东=`lidongdong`, 屈世雄=`qushixiong`, 郭雨濛=`guoyumeng`.
   - tycd project `1681`: 贾晓超=`jiaxiaochao`.
6. For mixed-service creation, write a short Python script that reuses one `ZentaoClient` login session per service. For each task:
   - `verify_task_created(project_id, name)` first to avoid duplicates after timeouts.
   - `create_task(project_id, name, module=..., assigned_to=..., task_type='devel', estimate=..., begin=..., end=..., desc=...)`；其余字段必须使用关键字参数。
   - `verify_task_created(...)` again to recover task ID if the create response only locates the task list.
   - `get_task_detail(task_id)` and verify `project`, `module`, `assignedTo`, `estimate`, `left`, `estStarted`, and `deadline`.
7. Generate one screenshot per service using the last task ID for that service:
   - typm: `python3 scripts/zentao-screenshot-task.py <taskID> 'typm 科技禅道' <projectID>`
   - tycd: `python3 scripts/zentao-screenshot-task.py <taskID> 'tycd 田一禅道' <projectID>`
   Then visually check that the screenshot contains the target task ID/name and the correct service/project.
8. Only after live ZenTao verification succeeds, update the local `teamlog` rows in place with service, project, module, task ID, deadline, and a progress note summarizing task IDs, dates, verification, and screenshot paths. Run an ad-hoc verification script against the affected section before replying.

## Reporting

Return a compact table of participant ID → task ID, service, project/module, assignee, estimate, and dates. Include one screenshot per service with `MEDIA:<path>`.
