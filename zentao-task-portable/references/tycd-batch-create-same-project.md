# 田一禅道同项目批量创建任务

同一项目的一条或多条创建请求统一走版本化两调用流程，预检和批准执行是唯一编排入口。

## 流程

1. 将用户给出的田一禅道、项目、模块、负责人、任务名和工时写入请求 JSON；项目、leaf 模块和中文负责人可以保留普通名称。
2. 运行一次预检并保存输出：

```bash
python3 "$SKILL_DIR/scripts/zentao-create-task-refactored.py" --batch-json request.json --dry-run > approved-plan.json
```

3. 普通消息展示批准计划中的服务、项目、模块、负责人、工时和日期。若返回 `needs_confirmation`，只展示其中的相关候选，更新请求后重新预检。
4. 用户明确确认后执行同一份计划：

```bash
python3 "$SKILL_DIR/scripts/zentao-create-task-refactored.py" --approved-plan approved-plan.json
```

5. 只按执行 JSON 报告任务。执行器负责精确同名复用、写结果未知恢复、详情读回和整批单截图。

## Reporting

返回任务 ID、名称、项目、模块、负责人、类型、estimate、left、begin、deadline、source 和截图路径。
