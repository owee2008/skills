# 修改任务

用于处理“改任务标题/模块/工时/日期”等请求。

## 可修改字段

| 参数 | 禅道字段 | 说明 |
|------|----------|------|
| `--name` | `name` | 标题 |
| `--module` | `module` | 模块 ID |
| `--estimate` | `estimate` | 预计工时 |
| `--left` | `left` | 剩余工时 |
| `--start-date` | `estStarted` | 开始日期 |
| `--deadline` | `deadline` | 截止日期 |

## 命令

```bash
./scripts/zentao-edit-task.py <任务ID> --name "新标题"
./scripts/zentao-edit-task.py <任务ID> --estimate 8 --left 6 --deadline 2026-05-20 --yes
./scripts/zentao-edit-task.py <任务ID> --project-id <项目ID> --module <模块ID>
./scripts/zentao-edit-task.py --user-text "在科技部门禅道" <任务ID> --name "新标题"
./scripts/zentao-edit-task.py <任务ID> --wizard
```

## 模块修改安全规则

修改模块时必须：

1. 获取并展示目标项目的完整模块列表。
2. 要求用户显式提供模块 ID，或在向导里明确选择。
3. 禁止按任务标题自动推断模块。
4. `--yes` 只能跳过最终确认，不能跳过模块显式选择和模块列表校验。

## 验证

修改完成后读取脚本输出。若用户要求可视化确认，使用 `query.md` 中的截图流程。
