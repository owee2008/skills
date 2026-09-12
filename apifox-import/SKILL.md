---
name: apifox-import
description: 上传或更新 Apifox 接口文档、集成测试用例和场景定义，并回查保存结果。按项目/模块映射定位目标，使用 APIFOX_ACCESS_TOKEN 鉴权；不执行测试。
---

# Apifox 接口与集成测试上传

优先使用服务端 API，读取元数据时可用已连接的工具或官方 CLI。用户要求上传/更新指定接口或测试定义即为该次写入的授权；预览不执行写入。技能不管理登录凭据、不修改项目权限，也不发布公开文档站。

## 定位目标

- 在项目/模块内操作时，统一使用项目根目录下的 `docs/apifox.md` 维护接口与 Apifox 的关联；先读取该文档，AGENTS.md 中的相关指针也应指向此路径。非项目上下文按用户指定的映射定位。
- 按**当前仓库 + 模块**匹配 projectId、folderId、API 服务地址和目标分支，不能把其他项目的 ID 当默认值。
- 映射缺失时，用只读项目/目录/接口列表定位。唯一候选可以直接采用；存在多个候选或目标分支不明时，只询问缺失的决定，不重问已确认内容。
- 写入前核对项目名称/ID、目录归属，以及待导入的 method/path 是否已经存在。目录存在性应查完整目录树或已有接口的 folderId，不能用“某目录下没有子目录”证明目录存在。
- 目标分支按下方“上传前准备同名分支”确定，映射中的历史分支仅供定位。私有化部署先确认服务地址和读写工具支持，再使用对应凭据，不能试发到公有云。

仓库映射建议格式（示例 ID 不是真实配置）：

```markdown
# Apifox 映射
API 服务地址：https://api.apifox.com
令牌环境变量：APIFOX_ACCESS_TOKEN

| 仓库 | 模块识别名 | projectId | 项目名 | folderId | 分支 |
|---|---|---:|---|---:|---|
| example-service | 群成员接口 | 123456 | example-service | 789012 | 与本地 Git 当前分支同名 |
```

项目内所有接口及对应 Apifox 地址统一归档到 `docs/apifox.md`，按模块维护；文档不存在时创建，存在时增量更新并保留其他模块记录。每条接口记录方法、完整路径、用途、projectId、folderId、分支、接口 ID 和 Apifox 页面链接，区分业务请求地址与 Apifox 管理 API 服务地址。链接和 ID 使用实际查询或上传回查结果，尚未确认的值标为“待确认”，不拼造地址。

例如：`群成员接口 | POST /im/groups/members/transfer-owner | 群主转让 | 接口 ID：待确认 | Apifox 链接：待确认`。上传并回查后更新本次接口记录，已有其他接口关联继续保留；整理全部接口关联不代表授权上传全部接口。技能安装不自动修改各项目的 AGENTS.md。

## 上传前准备同名分支

接口文档、用例、场景定义上传均先完成以下步骤，再进行内容写入：

1. 在实际业务仓库执行 `git branch --show-current`，取得完整分支名。例如本地为 `feat/group-owner-transfer`，Apifox 目标也必须为 `feat/group-owner-transfer`，保留斜杠，不添加 `ai/` 或日期前缀。非 Git 目录或 detached HEAD 无法取得名称时，先向用户确认本地分支名，不使用 skill 所在目录的分支代替。
2. 查询目标项目的分支，按完整名称精确匹配。同名分支已存在时核对类型和可写性后复用；不存在时先核对真实来源分支，再创建同名分支。创建属于本次上传的前置操作，已有上传授权时无需另行确认。来源有多个且无法确定时只询问来源。
3. 使用脚本创建 AI 分支时，命令为 `branch create --project <项目ID> --type ai --name <本地分支名> --from <已确认来源分支>`，先预览再 `--apply`。若平台不接受该名称或同名分支不可写，报告阻碍，不自行改名或换分支。创建结果不确定时先回查，确认未创建后才重试。
4. 回查确认项目、完整分支名及真实分支 ID 后，上传和回查均显式指定该分支；接口、用例和场景保持在同一分支。记录分支名称和 ID 到项目的 `docs/apifox.md`。

本技能的 REST `import` 子命令仅写默认主分支，不支持指定分支，不能用于本流程的上传。使用具备分支能力的官方 CLI，先检查当前命令帮助及 schema，再显式指定同名分支写入；工具无法指定或核实目标分支时停止上传。不得先上传主分支再补建分支。

## 凭据与工具

统一读取执行环境的 `APIFOX_ACCESS_TOKEN`。缺失时提示配置该变量并停止认证操作，不搜索 Vault、桌面登录数据或其他凭据来源；不要输出令牌、写入 Git 或执行持久化登录。

使用 [scripts/apifox.py](scripts/apifox.py)：只依赖 Python 标准库。`cli` 支持只读发现/回查以及受限的定义写入（默认预览，需 `--apply`）；不支持 run/delete/merge/login。令牌通过子进程环境传递，在 Node 内存中组装 CLI 参数，不出现在系统命令行。

先复用已安装的 `apifox` 或现有 npm 缓存。找不到 CLI 时才安装/缓存官方工具，且安装过程不携带令牌；已验证版本为 `apifox-cli@2.2.9`：

```sh
env -u APIFOX_ACCESS_TOKEN npx -y apifox-cli@2.2.9 --help
python3 <skill目录>/scripts/apifox.py cli --name-contains <项目关键词> -- project list
python3 <skill目录>/scripts/apifox.py cli -- folder list --project <项目ID> --type endpoint
python3 <skill目录>/scripts/apifox.py cli -- endpoint list --project <项目ID> --path-contains <接口路径>
```

不读取 CLI 的整份打包 JS（可能几十 MB）；选项不明确时先看 `--help`。工具已可用时不重复安装或研究替代连接方案。

## 选择上传内容

- 接口文档：按下方“导入接口”处理。
- 集成用例/场景：读取 [references/integration-tests.md](references/integration-tests.md)，按其绑定、组装和回查规则上传。
- 两者都需要：先保存接口并拿到真实ID，再绑定测试用例。
- 请求执行测试：交给独立执行流程；本技能不把“保存用例”扩展为“运行真实请求”。运行流程可以复用项目映射和上传后的资源ID，但须单独处理测试数据、结果与清理。

## 导入接口

1. 从本次代码/契约生成**仅包含授权接口**的 OpenAPI JSON；请求字段、必填性、响应与示例应与实现一致。优先内联 schema，避免覆盖共享模型。外部引用先打包为本地引用。
2. 显式指定目标目录时，避免 `tags` 或 `x-apifox-folder` 意外创建额外目录层级；保留标签有必要时先确认导入行为。样例只用占位数据，鉴权头写环境占位值，不能填真实密钥。
3. 完成“上传前准备同名分支”，使用支持分支的 CLI 预览同一份文件、项目和分支，确认 method/path 清单；已有上传授权时直接继续 `--apply`，无需再次询问是否执行。

按准确 method/path 匹配同名分支内的接口后创建或更新，保留无关资源和已有公共模型，不启用删除未匹配资源的模式。根目录必须显式指定，不能拿它代替未知目录。

## 回查与停止条件

- HTTP 200 和导入 counters 仅表示收到导入响应，**不等于已完成**。用 `endpoint list` 找到每条准确 method/path，再用 `endpoint get` 核对项目/目录、请求字段与必填约束、响应及关键示例；检查无关接口仍保留。
- CLI `--path-contains` 是包含匹配，必须再比较完整路径，避免把相似路径当作目标。
- 超时、断连、非 JSON 或不确定响应：先回查，确认已生效则结束；确认未生效后才决定是否重试。不能用新请求反复试写来判断结果。
- 不自动更改 AI 编辑权限、不绕过服务端拒绝。读写能力不足时报告确切阻碍及已完成部分。
- 最终报告项目/分支、接口或测试资源ID、创建/更新数量和回查结论；测试定义明确标注未执行。没有回查证据时标为未确认，不声称上传成功。

官方协议：[导入 API](https://apifox-openapi.apifox.cn/api-173409873)、[鉴权](https://apifox-openapi.apifox.cn/doc-4296599)、[CLI](https://docs.apifox.com/cli-command-options)。已验证公有云请求头 `X-Apifox-Api-Version: 2024-03-28`；接口版本被拒绝时查官方契约，不猜新参数。
