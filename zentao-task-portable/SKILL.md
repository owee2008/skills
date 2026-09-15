---
name: "zentao-task"
description: "安全创建、查询、修改和关闭田一或科技禅道任务；工时调整同步剩余工时"
---

# zentao-task

仅在用户明确操作禅道任务时使用。先按请求路由到相应短文档，禁止每次加载全部历史案例。

## 工作区与凭据

产物必须写到调用方工作区，不能写入 Skill 安装目录：

```bash
export ZENTAO_WORKSPACE_DIR="/path/to/agent-workspace"
mkdir -p "$ZENTAO_WORKSPACE_DIR/zentao-artifacts"
```

脚本从 `VAULT_ADDR`、`VAULT_TOKEN` 读取凭据。缺少或不可用时，停止在只读草案，说明 Vault 问题；不得猜测凭据、搜索用户目录或输出 token/password。

## 路由

| 用户意图 | 先读 | 执行入口 |
|---|---|---|
| 创建一条或一批任务 | `create.md` | `scripts/zentao-create-task-refactored.py` |
| 查询任务或截图 | `query.md` | 查询/截图脚本 |
| 改标题、模块、日期或工时 | `edit.md` | `scripts/zentao-edit-task.py` |
| 完成、关闭、批量补工时、迁移项目 | 对应 `references/*.md` | 先只读任务与表单，再按参考流程操作 |

只在需要时读取：模块归属读 `references/real-module-selection.md`；项目歧义读 `references/tycd-app-install-project-disambiguation.md`；批量创建读 `references/tycd-batch-create-same-project.md`；批量工时读 `references/effort-log-batch-operations.md`。参考资料是历史线索，不是实时事实。

## 创建任务安全流程

1. 从用户请求提取服务、项目、模块、负责人、标题、类型、工时和日期。
2. 项目不明确才查询项目；模块不明确才查询目标项目模块；中文负责人未知才读取目标项目创建页确认账号。不要用静态映射替代实时结果。
3. 将完整清单作为普通消息展示：服务、项目/模块 ID、负责人账号、标题、预计和剩余工时、日期、类型。批量任务必须整批确认。
4. 用户回复“确认创建”等明确授权后才可写入；如果用户改了任务明细，视为替换草案，重新展示清单。
5. 批量时使用同一个 CLI 和同一个会话：先 `--dry-run`，确认后去掉该参数执行。创建后必须精确名称查重并读回项目、模块、负责人、`estimate`、`left`、日期和类型。

批量清单示例：

```json
{
  "project_id": 1681,
  "user_text": "tycd 田一禅道",
  "tasks": [
    {
      "name": "行程轨迹异常状态字段",
      "module": 9701,
      "assigned_to": "zhangbin",
      "estimate": 2,
      "task_type": "devel",
      "begin": "2026-09-01",
      "end": "2026-09-10"
    }
  ]
}
```

```bash
python3 scripts/zentao-create-task-refactored.py --batch-json tasks.json --dry-run
python3 scripts/zentao-create-task-refactored.py --batch-json tasks.json
```

`--dry-run` 只登录和校验项目状态、真实模块、负责人下拉及清单，绝不创建任务。单任务旧位置参数继续可用。

## 不可突破的规则

- 混合 tycd/typm 关键词时先让用户选择服务；不能依赖关键词优先级直接创建。
- 模块必须属于实时目标项目；优先 leaf 模块。项目关闭、没有模块或创建页拒绝时停止。
- 不根据中文姓名猜禅道账号；不因其它项目可选而假设目标项目可指派。
- 创建 POST 超时后先精确查询同项目同名任务，确认不存在才重试。
- 修改未完成任务工时且用户未限定字段时，`estimate` 与 `left` 同步增减；已完成任务先读取并取得明确确认，`left` 保持 `0`。
- 最终回复只报告读回验证的事实；截图、备份等产物保存在工作区。
