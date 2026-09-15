# 创建任务

用于处理“创建禅道任务”“给某项目加任务”“批量创建任务”等请求。

## 标准流程

1. 收集任务信息：项目 ID、任务标题、模块、负责人、类型、预计工时、开始日期、截止日期。
2. 仅当项目 ID 缺失时才查询项目；模块 ID 缺失时查询目标项目完整模块列表并让用户选择，禁止自动决定模块。
3. 确认默认值：类型 `devel`、预计工时 `10`、开始日期 `T-5`、截止日期 `T+10`。
4. 批量任务先保存为 JSON 清单，运行 `--dry-run`，将预检结果作为普通消息回显，等待“确认创建”。
5. 确认后调用创建脚本；脚本会精确查重、创建并读回验证。

## 命令

```bash
./scripts/zentao-create-task-refactored.py <项目ID> "<任务标题>" <模块ID>
./scripts/zentao-create-task-refactored.py <项目ID> "<任务标题>" <模块ID> <负责人> <类型> <工时> <开始日期> <截止日期>
./scripts/zentao-create-task-refactored.py --user-text "在科技部门禅道" <项目ID> "<任务标题>" <模块ID>
./scripts/zentao-create-task-refactored.py --wizard
```

批量创建使用一个会话，避免逐条登录和临时代码：

```json
{
  "project_id": 1681,
  "user_text": "tycd 田一禅道",
  "tasks": [
    {"name": "行程轨迹异常状态字段", "module": 9701, "assigned_to": "zhangbin", "estimate": 2}
  ]
}
```

```bash
python3 ./scripts/zentao-create-task-refactored.py --batch-json tasks.json --dry-run
python3 ./scripts/zentao-create-task-refactored.py --batch-json tasks.json
```

`--dry-run` 只读取项目状态、模块和负责人下拉，绝不提交创建请求。实际创建后，输出以读回的项目、模块、负责人、`estimate`、`left`、日期和类型为准。

完整示例：

```bash
./scripts/zentao-create-task-refactored.py 1681 "开发智能体任务看板筛选功能" 9706 zhouwei devel 8 2026-05-17 2026-05-27
```

测试/示例任务在非交互环境下需要显式加 `--force`：

```bash
./scripts/zentao-create-task-refactored.py 1681 "测试任务" 0 --force
```

## 字段规则

| 字段 | 规则 |
|------|------|
| 项目 ID | 必填；不知道时先查项目列表 |
| 任务标题 | 必填；保持用户原意，不随意改写 |
| 模块 ID | 必填；`0` 表示无模块，但必须经过确认 |
| 负责人 | 可选；未指定时脚本默认 `zhouwei` |
| 类型 | 可选；常用值：`design`、`devel`、`test`、`study`、`discuss`、`ui`、`affair` |
| 预计工时 | 可选；未指定默认 `10` 小时 |
| 开始日期 | 可选；格式 `YYYY-MM-DD`，未指定默认 `T-5` |
| 截止日期 | 可选；格式 `YYYY-MM-DD`，未指定默认 `T+10` |

## 成功回复要求

最终回复至少包含：

- 是否创建成功
- 任务 ID（如果脚本返回）
- 任务标题
- 项目 ID 和模块 ID
- 负责人、预计工时、预计开始日期、截止日期
- 使用的禅道服务地址或部门

如果脚本生成截图，创建成功后把截图路径或发送结果一并说明。
