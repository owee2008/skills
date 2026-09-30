---
name: git-branch-governance
description: "按 dev、test、main 与 feature/hotfix 分支职责引导并执行 Git 开发流程。用于创建分支、提测、选择性上线、同步开发基线、热修复及历史改写前的安全决策。"
---

# Git Branch Governance

将分支当成可追溯的交付单元。目标是让每个功能能独立开发、提测与上线，而不是让 Git 图保持直线。

## 长期分支职责

- `main`：生产事实。仅包含已正式上线的提交；不为测试直接合入内容。
- `test`：测试环境分支。它可以顺序合入所有需要测试的 `feature/*`，形成 10 个或更多集成 merge；不代表下一次发布版本。
- `gray/*`：灰测发布分支。从 `main` 创建，选择已在 `test` 验证通过的功能组成干净候选版本；灰测通过后才合入 `main`。
- `dev`：开发基线。只从 `main` 接收已上线内容；不要把 `test`、`gray/*` 或 `feature/*` 直接合入 `dev`。
- `feature/*`：单一功能或需求的完整交付分支。
- `hotfix/*`：从当前 `main` 临时创建的线上紧急修复分支。

默认流程是 `dev -> feature/* -> test`；选择性上线时使用 `main -> gray/* -> main -> dev`。除非用户明确指定测试集整体就是发布版本，禁止默认执行 `test -> main`。除 `hotfix/*` 与 `gray/*` 外，`dev` 只创建 `feature/*`。

## 作者身份与默认 Git 配置

提交、创建分支或推送前，读取并校验当前仓库的 `user.name` 与 `user.email`。团队规范如下：

- `user.email` 必须以 `@tycmc.net` 结尾；不符合时停止写入操作，提示用户配置公司邮箱。
- `user.name` 使用本人汉语拼音、全小写、无空格；例如张三使用 `zhangsan`。只可自动校验为全小写英文字母，不能凭规则判断它是否确实属于当前用户。
- 配置身份时，不猜测真实姓名或邮箱。先由用户提供精确值，再明确说明是写入当前仓库还是全局配置。

身份配置示例：

```bash
git config user.name zhangsan
git config user.email zhangsan@tycmc.net
```

默认仅允许快进合并：`git config --global merge.ff only`。普通分支合并不能快进时必须失败，不得悄悄创建 merge commit。

`test` 是唯一的常规例外：为保留“哪个功能何时进入测试环境”的集成记录，按提测清单显式执行 `git merge --no-ff feature/<name>`。这不是默认行为，也不应在 `main`、`dev` 或 `gray/*` 上隐式使用。

## 每次开发开始前

在任何创建、合并、rebase、reset、cherry-pick 或 push 前，先只读确认：当前分支、工作区状态、远端、`dev/test/main` 是否存在，以及目标分支和基线的提交关系。

若用户没有给足信息，询问以下最少信息后再创建分支：

1. 需求名称或工单号，用于确定 `feature/<name>`、`fix/<name>` 或 `hotfix/<name>`。
2. 是否为共享分支；共享分支不重写公开历史。
3. 基线分支；普通开发默认 `dev`，紧急生产修复默认 `main`。
4. 是独立上线，还是只先进入测试集成区。

普通功能的起点示例：

```bash
git switch dev
git pull --ff-only
git switch -c feature/订单导出
```

不要在工作区有未解释改动时切换或重写分支；先向用户说明状态并保留其改动。

## 八类场景的路由

| 场景 | 分支动作 |
| --- | --- |
| 单功能正常上线 | `dev -> feature/* -> test`；验证后由 `main` 创建 `gray/*`，带入该功能，灰测通过再合入 `main -> dev`。 |
| 多功能并行 | 每个功能分别从 `dev` 创建独立 `feature/*`，按提测清单依次合入 `test`；`test` 可以保留多个 merge 节点。 |
| 选择性上线 | `test` 可有 A/B/C/D；仅发布 D 时从 `main` 创建 `gray/*`，只带入 D，不能整体 `test -> main`。 |
| 开发中 dev 更新 | 个人未共享 feature 可 `rebase dev`；多人共享 feature 使用 `merge dev`。 |
| 线上紧急 Bug | `main -> hotfix/* -> main -> dev`；不要从 `dev` 开始热修复。 |
| 长周期 Feature | 在准备提测、周期较长或基线变更相关时同步 `dev`；不要为形式而频繁同步。 |
| 成熟项目并行 | 接受正常 DAG；用分支职责、PR 与可独立交付判断健康度。 |
| 高复杂度并发 | 分开记录功能提测、生产上线、热修复与回同步；不要为了直线历史混合职责。 |

## 测试、灰测与上线

- `test` 对应测试环境。每个已完成且需要测试的 `feature/*`，按提测清单显式以 `--no-ff` 合入 `test`；10 个功能可以有 10 个 test merge。
- 测试期间的修复必须先回到对应 `feature/*`，再让 `test` 获得该修复；不得只在 `test` 留修复。
- 选择性上线时，从当前 `main` 创建 `gray/<release-name>`。`gray/*` 只包含本次批准上线、且已在 `test` 验证的功能。
- Git 不能“部分 merge 一个分支”。要从 `test` 取部分内容，先在 `test` 的 first-parent 历史中定位对应 feature 的 merge，再由该 `feature/*` 合入 `gray/*`；若只取功能中的指定提交，使用经确认的 `cherry-pick` 提交列表。不得直接把整个 `test` 合入 `gray/*`。
- 灰测通过后，将 `gray/*` 合入 `main`；确认生产上线后，`main` 是唯一允许合入 `dev` 的来源。`dev` 只再派生新的 `feature/*`。
- 上线前说明候选 feature、`main` 当前状态、每个候选在 `test` 的验证证据和灰测结果。
- 所有服务器部署、远端强推、删除远端分支必须在执行前得到明确授权。

## 历史改写与对象安全

- fast-forward merge 只移动分支指针，不产生新 commit。
- `rebase`、`rebase -i`、`cherry-pick`、`commit --amend` 会创建新 commit ID；删除中间提交会重写其后全部提交。
- 已推送且由他人使用的分支，默认不要 rebase 或强推。确需重写时，先说明影响范围，并仅在明确授权后使用 `--force-with-lease`。
- `cherry-pick` 适合选择性带入单个修复；后续再合并原分支时要检查重复改动和冲突风险。
- 不可达提交可能暂时存在于 reflog；发现误操作优先只读运行 `git reflog`，不要立刻执行激进 GC 或清理命令。

## 每个动作后的汇报

完成一个独立阶段后，简短报告：当前分支、目标分支、是否产生新 commit、是否改变既有 commit ID、测试或检查结果，以及下一步是否需要用户授权。不要把“已推送”表述为“已上线”；部署完成需有环境验证证据。
