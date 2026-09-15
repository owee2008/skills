# 田一禅道：重复工时日志扫描、删除与剩余工时恢复

## 适用场景

用户给出一个或多个田一禅道任务 ID，要求检查某些日期或全部工时日志是否有重复，并在确认后删除重复日志。

## 重复判定口径

默认“明确重复”口径：同一任务、同一日期、同一账号、同一 consumed 工时、同一 work 文本完全一致。

```sql
select e.id,e.date,e.account,u.realname,e.consumed,e.`left`,e.work,e.project,e.objectID,e.objectType,
       t.name as taskName,e.product
from zt_effort e
left join zt_user u on u.account=e.account
left join zt_task t on t.id=e.objectID and e.objectType='task'
where e.objectType='task' and e.objectID in (<task_ids>)
  -- 如用户指定日期：and e.date in ('YYYY-MM-DD', ...)
order by e.objectID asc,e.date asc,e.account asc,e.work asc,cast(e.consumed as decimal(10,2)) asc,e.id asc;
```

在 Python 侧按 key 分组：

```python
key = (objectID, date, account, str(consumed), work.strip(), objectType)
```

每组保留最早/最小 ID 的日志，建议删除后续重复 ID。若同日同工时但 work 仅有细微文字差异（如“日报告/日报”），只能标注“疑似重复”，不要自动删除，先让用户确认。

## 删除前确认与备份

1. 普通聊天消息展示每个任务的重复组、建议保留 ID、建议删除 ID、重复工时合计。
2. 等用户明确“确认删除”后再写操作。
3. 删除前备份到 `$WORKSPACE_DIR/zentao-change-backups/`，至少包含：
   - 目标任务 `zt_task` 行；
   - 目标任务全部 `zt_effort` 行；
   - 待删除的 `zt_effort` 行；
   - 删除 ID 列表和时间戳。

## 删除执行

必须走官方接口，不要直接 SQL 删除：

```python
client.get(f"/effort-delete-{effort_id}-yes.html")
```

每删一条立即查询验证：

```sql
select id from zt_effort where id=<effort_id>;
```

最终再查询所有目标 ID，要求返回空。

## 删除后的任务字段处理

删除工时后，禅道通常会自动重算 `zt_task.consumed`，但 `left` 可能仍停留在旧值。

### 未完成任务（doing 等）

按用户已确认口径：删除重复日志后主动恢复剩余工时：

```text
new_left = estimate - consumed
```

若 `left != new_left`，用任务编辑脚本更新：

```bash
cd "$SKILL_DIR" \
  && python3 scripts/zentao-edit-task.py --user-text 'tycd 田一禅道' <task_id> --left <new_left> --yes
```

提交后重新读回 `zt_task` 验证 `estimate/consumed/left/status`。

### 已完成任务（done）

只删除重复执行并让总耗时随禅道重算；不要改任务状态，不要把 `left` 改成 `estimate - consumed`。读回确认：

- `status` 仍为 `done`；
- `left` 仍为 `0`；
- `finishedBy` / `finishedDate` 未被改变；
- `consumed` 已减少到删除后的实际总耗时。

## 最终回复

必须列出：

- 删除的日志 ID 和工时合计；
- 备份文件路径；
- 每个任务删除后的 `status/estimate/consumed/left`；
- 未完成任务的剩余工时计算式；
- 已完成任务说明“未改状态，left 保持 0”。
