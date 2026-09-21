---
name: "zentao-task"
description: "安全创建、查询、修改和关闭田一或科技禅道任务；工时调整同步剩余工时"
metadata:
  version: "1.7"
---

# zentao-task

仅在用户明确操作禅道任务时使用。先按请求路由到相应短文档，禁止每次加载全部历史案例。

## 工作区与凭据

产物必须写到调用方工作区，不能写入 Skill 安装目录：

```bash
export ZENTAO_WORKSPACE_DIR="/path/to/agent-workspace"
mkdir -p "$ZENTAO_WORKSPACE_DIR/zentao-artifacts"
```

凭据来源按优先级（实现在 `scripts/zentao_common.py` 的 `VaultClient.__init__`）：

1. 显式入参 `VaultClient(token=…, addr=…)`
2. 环境变量 `VAULT_TOKEN` / `VAULT_ADDR`（addr 默认 `http://127.0.0.1:8200`）
3. 文件 `~/.vault-token`（Vault CLI 约定位置，权限必须为 `600`）

第 3 条为什么存在：由 GUI（Dock / Finder）启动的进程不加载 `~/.zshrc`，只继承 launchd 环境，所以 `VAULT_TOKEN` 常常取不到；读约定位置的凭据文件可绕开这条继承链。

**凭据读取边界（不可突破）**

- 只允许读 `~/.vault-token` 这一个约定位置。**不得扫描、遍历或搜索其它用户目录寻找凭据**，不得从 `~/.zshrc`、`.bashrc`、`.profile` 等 shell 配置文件中提取凭据。
- 缺少或不可用时，停止在只读草案，说明 Vault 问题；不得猜测凭据。
- 任何输出（含调试、报错、日志）中都不得回显 token 或 password。

## 路由

| 用户意图 | 先读 | 执行入口 |
|---|---|---|
| 创建一条或一批任务 | `create.md` | `scripts/zentao-create-task-refactored.py` |
| 查询任务或截图 | `query.md` | 查询/截图脚本 |
| 改标题、模块、日期或工时 | `edit.md` | `scripts/zentao-edit-task.py` |
| 完成、关闭、批量补工时、迁移项目 | 对应 `references/*.md` | 先只读任务与表单，再按参考流程操作 |

只在需要时读取：模块归属读 `references/real-module-selection.md`；项目歧义读 `references/tycd-app-install-project-disambiguation.md`；批量创建读 `references/tycd-batch-create-same-project.md`；批量工时读 `references/effort-log-batch-operations.md`。参考资料是历史线索，不是实时事实。

## 创建任务安全流程

1. 从用户请求提取服务、项目、模块、负责人、标题、类型、工时和日期，名称可直接写入请求清单。
2. 运行一次 `--batch-json <request> --dry-run`。脚本在同一会话内实时解析并校验项目、leaf 模块和负责人；唯一命中时输出版本化批准计划，歧义时只输出相关候选。项目、模块和负责人事实只由这次预检实时解析；帮助探测、独立列表查询、源码检查和临时 Python 不属于创建流程。
3. 将批准计划中的完整清单作为普通消息展示：服务、项目/模块 ID、负责人账号、标题、预计和剩余工时、日期、类型。批量任务必须整批确认。
4. 用户修改草案时更新原请求清单并重新预检。用户明确确认后，使用同一份计划运行一次 `--approved-plan <plan>`；不能手工改写已批准的 ID 或账号。
5. 执行器重新校验批准事实、精确同名查重、恢复写结果未知的请求并读回关键字段；最终回复只使用执行 JSON 中的验证结果。

批量清单示例：

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
      "task_type": "devel",
      "begin": "2026-09-01",
      "end": "2026-09-10"
    }
  ]
}
```

```bash
python3 scripts/zentao-create-task-refactored.py --batch-json request.json --dry-run > approved-plan.json
python3 scripts/zentao-create-task-refactored.py --approved-plan approved-plan.json
```

`--dry-run` 只登录和校验，绝不创建任务；`--approved-plan` 只接受版本化预检输出。旧位置参数和旧 batch JSON 执行方式保留兼容，但新流程统一使用批准计划。

## 不可突破的规则

- 混合 tycd/typm 关键词时先让用户选择服务；不能依赖关键词优先级直接创建。
- 模块必须属于实时目标项目；优先 leaf 模块。项目关闭、没有模块或创建页拒绝时停止。
- 不根据中文姓名猜禅道账号；不因其它项目可选而假设目标项目可指派。
- 创建 POST 写结果未知时由执行器精确查询同项目同名任务；未命中即失败，不自动重复 POST。
- 修改未完成任务工时且用户未限定字段时，`estimate` 与 `left` 同步增减；已完成任务先读取并取得明确确认，`left` 保持 `0`。
- 最终回复只报告读回验证的事实；截图、备份等产物保存在工作区。
