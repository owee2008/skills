# 禅道参考信息

按需读取本文件；不要把这里的内容当作实时事实。禅道项目、模块和界面字段可能变更，执行前优先用脚本验证。

## 常见任务类型

| 中文 | 值 |
|------|----|
| 设计 | `design` |
| 开发 | `devel` |
| 测试 | `test` |
| 研究 | `study` |
| 讨论 | `discuss` |
| 界面 | `ui` |
| 其他 | `affair` |

## 常见 Web/API 形态

创建任务常见接口：

```text
POST /zentao/task-create-{projectID}.json
```

常见字段：

```json
{
  "project": "项目ID",
  "module": "模块ID",
  "name": "任务名称",
  "desc": "任务描述",
  "type": "任务类型",
  "pri": "优先级(1-4)",
  "estimate": "预计工时(小时)",
  "estStarted": "预计开始日期(YYYY-MM-DD)",
  "deadline": "截止日期(YYYY-MM-DD)",
  "assignedTo": "指派给(用户名)"
}
```

项目列表常见接口：

```text
GET /zentao/project-browse.json
```

模块列表常见接口：

```text
GET /zentao/tree-browse-task-{projectID}.json
```

## 常见页面字段

任务创建页常见 URL：

```text
https://tycd.tygps.com/project-task-create-{projectId}.html
```

表单字段：

- `input[name="name"]`：任务名称
- `select[name="module"]`：所属模块
- `select[name="assignedTo"]` 或 `input[name="assignedTo"]`：指派给
- `select[name="type"]`：任务类型
- `input[name="estimate"]`：预计工时
- `input[name="estStarted"]`：预计开始
- `input[name="deadline"]`：截止日期
- `textarea[name="desc"]`：任务描述
- `select[name="pri"]`：优先级

## 日期

脚本参数优先使用 `YYYY-MM-DD`。相对日期如“明天/下周三”需要先转换为具体日期再传入脚本。
