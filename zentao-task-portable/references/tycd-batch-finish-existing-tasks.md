# 田一禅道批量完成已有任务：表单 JSON 路径

## 适用场景

用户要求将一批田一禅道（`tycd.tygps.com`）已有任务标记为完成/已完成/结束，并且任务当前通常是 `wait`，有 `estimate`、`consumed`、`left` 字段。

## 已验证流程

1. 复用一个 `ZentaoClient('https://tycd.tygps.com')` 登录会话。
2. 每个任务先 `get_task_detail(task_id)` 读取：`status`、`estimate`、`consumed`、`left`、`deadline`、`name`。
3. 已经是 `done` 或 `closed` 的任务跳过，不重复提交。
4. 对未完成任务：
   - GET `/biz/task-finish-<task_id>.html?onlybody=yes`
   - 用 `_ZentaoFormParser` 解析字段。
   - 本实例表单可能 `form_action=None`，但字段含：`consumed`、`assignedTo`、`finishedDate`、`labels[]`、`comment`。
   - 设置：
     - `consumed = 当前 consumed + 当前 left`；如果 `left<=0`，使用当前 `consumed`；如果仍为 0，可回退到 `estimate`。
     - `finishedDate = Asia/Shanghai 今天日期`
     - `comment = 用户给定备注`（如“任务已完成”）
     - 保留表单默认的 `assignedTo` 等其它字段。
   - POST `/biz/task-finish-<task_id>.json`，带请求头：
     - `Referer: <finish onlybody url>`
     - `X-Requested-With: XMLHttpRequest`
5. POST 后立即重新 `get_task_detail(task_id)` 验证：
   - `raw_fields.status == 'done'`
   - `left == 0`
   - `consumed` 为提交后的总消耗。

## 注意事项

- 不要优先使用旧的 `zentao-close-task.py` 浏览器自动化路径；它更慢且依赖 `agent-browser`。批量完成任务时，直接使用 finish 表单 + `.json` POST 更稳定。
- 完成动作的 `consumed` 表示任务总消耗，不是本次新增消耗。对于 `wait` 且 `consumed=0,left=estimate` 的任务，提交 `consumed=estimate` 会让任务完成并把 `left` 置 0。
- 最终回复必须列出每个任务的验证后状态、预计工时、消耗工时、剩余工时和完成时间。