# 创建任务

用于处理“创建禅道任务”“给某项目加任务”“批量创建任务”等请求。

## 标准流程

1. 把用户给出的服务、项目、模块、负责人、标题、类型、工时和日期写入一个请求 JSON。项目、模块和负责人可以直接使用普通名称。
2. 运行一次 `--batch-json request.json --dry-run > approved-plan.json`。脚本实时解析项目、leaf 模块和负责人，并返回紧凑确认计划或相关歧义候选；项目、模块和负责人事实由这次预检统一解析；独立列表、帮助探测、源码检查和临时 Python 不属于创建流程。
3. 将批准计划作为普通消息展示。缺字段或有歧义时更新请求 JSON 并重新预检；整批字段完整后等待用户明确确认。
4. 确认后运行一次 `--approved-plan approved-plan.json`。执行器重新校验数值项目/模块 ID 和负责人账号，再完成精确查重、创建、未知写恢复、读回验证和整批单截图。
5. 最终回复以执行 JSON 为准。

## 新流程

```json
{
  "project": "我的日志项目",
  "user_text": "田一禅道",
  "tasks": [
    {
      "name": "行程轨迹异常状态字段",
      "module": "行车模块",
      "assigned_to": "张斌",
      "estimate": 2,
      "task_type": "devel"
    }
  ]
}
```

```bash
python3 ./scripts/zentao-create-task-refactored.py --batch-json request.json --dry-run > approved-plan.json
python3 ./scripts/zentao-create-task-refactored.py --approved-plan approved-plan.json
```

`approved-plan.json` 必须是脚本输出的 `dry_run=true`、`status=ready`、`plan_version=1` 计划。用户修改任何业务字段后，应修改请求文件并重新预检，不能手工修改批准计划中的 ID 或账号。

## 兼容入口

以下旧入口继续可用，但新创建流程不再依赖它们：

```bash
./scripts/zentao-create-task-refactored.py <项目ID> "<任务标题>" <模块ID>
./scripts/zentao-create-task-refactored.py <项目ID> "<任务标题>" <模块ID> <负责人> <类型> <工时> <开始日期> <截止日期>
./scripts/zentao-create-task-refactored.py --batch-json legacy-tasks.json
./scripts/zentao-create-task-refactored.py --wizard
```

测试或示例任务在非交互执行旧入口时仍需显式添加 `--force`。

## 成功回复要求

最终回复至少包含任务 ID、标题、项目、模块、负责人、类型、预计工时、剩余工时、开始日期和截止日期，并说明任务是新建、精确复用还是未知写恢复。若执行结果含截图路径，一并返回。
