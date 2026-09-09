---
name: zentao-create-query
description: "Use when querying ZenTao projects, modules, or tasks, or creating ZenTao tasks. Uses Vault-held credentials; requires explicit confirmation before a creation write."
version: 1.1.0
---

# ZenTao: Query and Create Tasks

## Scope

This portable skill supports **read-only queries** and **task creation** for ZenTao instances compatible with the `/biz/` endpoints used by the bundled client. It intentionally excludes task edits, status changes, and effort-log changes.

## Safety Rules

- Read-only queries can run once the target ZenTao service is clear.
- Before creating any task, show a normal-chat final table with: service URL, project and ID, module and ID, assignee name/account, task title, type, estimate/left, start date, and deadline. Wait for explicit user authorization such as `确认创建`.
- Never invent a module. Query the target project's live module list first, or reuse a module proven by `zentao-recent-tasks.py` history. When a project has no matching module (e.g. no 鸿蒙 module), say so and propose the closest real module instead of guessing one.
- Treat a text containing both `tycd`/田一 and `typm`/科技/天远 as service ambiguity; ask the user to choose the URL before accessing either system.
- Credentials come only from Vault. Never put credentials, Vault tokens, cookies, or passwords in this skill, shell history, files, or output.
- After creation, use exact-name lookup within the project, then query task detail. Do not treat a substring match as proof of creation.
- If a creation request times out, first query by exact task name and project; retry only if it does not exist.

## Configuration

```bash
python3 -m pip install -r requirements.txt
export VAULT_ADDR='https://your-vault.example'
export VAULT_TOKEN='…'              # obtain from the receiving agent's secret manager
export ZENTAO_URL_DEFAULT='https://zentao.example'
# Optional explicit routes:
export ZENTAO_URL_TIANYI='https://tycd.example'
export ZENTAO_URL_KEJI='https://typm.example'
```

The default credential secret path is `secret/zentao/zhouwei` (with KV-v2 variants). If the receiving agent uses a different secret path/account, adapt `VaultClient.get_zentao_credentials()` in `scripts/zentao_common.py`; do not add a plaintext fallback.

## Query Commands

Run commands from this skill directory.

```bash
# List projects
python3 scripts/zentao-list-projects.py --user-text 'tycd 田一禅道'

# List modules in a project (project ID is positional)
python3 scripts/zentao-list-modules.py 1681 --user-text 'tycd 田一禅道'

# 按人查「最近」任务 —— 首选，用来锁定项目/模块/工时，避免反复问用户
python3 scripts/zentao-recent-tasks.py 周丙龙 --user-text '天远 typm' --projects 428
python3 scripts/zentao-recent-tasks.py zhoubinglong --user-text '天远 typm' --scan 8 --limit 15

# Query a task's live editable fields
python3 scripts/zentao-query-task.py 66798 --user-text 'tycd 田一禅道'
```

`zentao-recent-tasks.py` 只看最近、不扫全量：未给 `--projects` 时只扫 ID 最大的 `--scan`（默认 6）个最新项目，每个项目只取任务列表第一页的前 `--per-project`（默认 8）条命中。输出末尾给出「建议默认值」（项目 / 模块 / 工时 / 账号），可直接套用到建任务确认表。

## Create Command

```bash
# 单条
python3 scripts/zentao-create-task-refactored.py   --user-text '天远 typm'   <project_id> '<task title>' <module_id>   <assignee_account> <type> <estimate_hours> <start_YYYY-MM-DD> <deadline_YYYY-MM-DD>

# 批量（推荐 ≥2 条时使用：只登录一次，逐条回显任务 ID，末尾汇总）
python3 scripts/zentao-create-task-refactored.py --user-text '天远 typm' --batch /tmp/tasks.json
```

`tasks.json` 为数组（或 `{"tasks": [...]}`），元素字段：`project`、`name`、`module`、`assigned_to`、`type`、`estimate`、`begin`、`end`。

If dates are omitted, the bundled client uses `T-5` for start and `T+10` for deadline. Prefer passing resolved dates explicitly in automated workflows.

## 派工流程（先猜，再给备选）

1. 先跑 `zentao-recent-tasks.py` 拿到该成员的项目 / 模块 / 工时 / 周期默认值。
2. **一次给出完整确认表**：站点、项目（带 ID）、模块（带 ID）、指派人（姓名+账号）、类型、预计/剩余、开始、截止、任务名称。让用户一次性改完，不要按维度分多轮问。
3. 站点或项目有歧义时，**先给出一个带依据的默认猜测**（例如「按你上次的项目，默认 typm·428；若指的是田一站的『我的日志 1681』请说明」），同时列出备选，而不是把选择题原样抛回去。
4. 同名项目必须带站点前缀区分，例如 `typm·我的日志2026(428)` 与 `tycd·我的日志(1681)`。
5. 拿到 `确认创建` 后才执行。

## Verification

After successful creation:

1. Run `zentao-query-task.py <task_id>` against the same service.
2. Verify project, module, assignee (when exposed by the instance), type, estimate, left, start date, and deadline against the approved table.
3. Report only values read back from ZenTao.
