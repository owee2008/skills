# 上传集成测试定义

只创建/更新可运行定义，不执行请求。运行时测试数据、真实环境选择、测试执行、报告分析及恢复检查交给独立执行流程（建议另设 `apifox-test` 技能）。上传完成不代表测试通过。

## 准备与绑定

- 读取对应接口的当前请求/响应契约；查询同一项目、同一分支的已有用例和场景，按所属接口及明确名称匹配，避免重复创建。
- 用 `test-case category --project ...` 获取有效 categoryId；不能猜成1，否则可能创建成功但在界面不显示。
- `apiDetailId` 使用关联接口 ID。`responseId` 来自该接口的 `responses[]`，不是公共响应组件 ID。
- 场景的 folderId 来自 `folder list --type test-scenario`，不能复用接口目录 ID；根目录须明确指定0。
- 测试数据使用运行时变量，接口管理令牌和被测服务凭据分别表达。AI以后可生成请求ID并传入测试数据；真实群/账号/订单等必须来自指定测试资源，不能随机字符串冒充真实资源。

## 定义用例

每种资源在首次写入前读取当前 `cli-schema get`。脚本对带文件的写入在 `--apply` 时还会自动执行 schema 校验。

已验证的单接口用例格式：

- `apiDetailId`、有效 `categoryId`、`method`（小写）、`path`、`parameters`、`commonParameters` 和 `requestBody` 明确填写。
- `parameters` 包含 path/query/header/cookie 四个数组；没有覆盖公共参数时 `commonParameters={}`。
- JSON请求体放在 `requestBody.data` 字符串中，不是 rawData。
- 前后置操作使用 `{type, data, defaultEnable, enable}` 平铺结构；customScript 的 data 是JS字符串，不是嵌套config对象。
- 原生断言使用 `type=assertion`、`subject=responseJson/httpCode`、`comparison=equal`；复杂断言可以使用兼容Postman的 `pm.test`/`pm.expect`。
- 根据实现断言成功、明确失败、状态回查及清理结果，不能只看HTTP 200。真实集成用例不伪造Mock超时/500；结果未知时应停止并交给执行流程回查，不能当成预期失败通过。
- 有写入副作用的场景应有清晰前提、失败停止和恢复步骤。恢复步骤在正常顺序中不等于失败时必定自动执行，说明中要写清失败后的恢复责任。

```sh
python3 <skill目录>/scripts/apifox.py cli -- cli-schema get test-case-create
python3 <skill目录>/scripts/apifox.py cli -- test-case category --project <项目ID> --branch <分支>
python3 <skill目录>/scripts/apifox.py cli -- test-case create --project <项目ID> --branch <分支> --file <case.json>
# 以上写命令默认预览；确认输入符合用户授权后，在cli之后、--之前加 --apply。
```

## 同名分支中的接口准备

先按 [SKILL.md 的“上传前准备同名分支”](../SKILL.md#上传前准备同名分支) 完成分支创建或复用及回查，再上传用例和场景。

- 新建 AI 分支初始为空。需要复用已有接口时，用 `branch pick-to --project <项目ID> --type ai --from <已确认来源分支> --to <本地分支名> --endpoint-ids ...` 引入本次授权接口，再查询目标分支中的实际接口/响应 ID 绑定用例。
- 服务端返回 `Automation caller branch required` 时停止写入并核对同名分支类型及可写性；不另建带前缀或日期的分支，不改权限绕过限制。
- 记录同名分支及用例、场景 ID。合并是独立动作，本上传脚本不执行 merge。

## 组装场景

- 先创建场景壳：`test-scenario create`，填写 name、description、folderId、priority。
- **创建时传steps不会保存**。创建后使用 `test-scenario import-steps <ID> --source test-case --endpoint <接口ID> --ids <用例ID列表> --sync manual`。
- 拿到创建/查询返回的真实场景和用例ID后才关联；预览阶段没有新资源ID时，只说明下一步，不以占位ID执行关联。
- 按预期顺序导入；连续属于同一接口的用例可以一批导入，减少请求次数。
- 回查运行选项；create可能未持久化options。需要时在get现状后只更新完整options对象，例如 `onError=end`、`saveReportDetail=none`，不替换步骤。
- 修改数组/嵌套对象前先get完整资源；调整步骤图须 `get --with-case-detail`，保留完整已有结构后再update。标量名称/说明可单独更新。

## 回查与交接

- 用例get核对所属接口、有效分组、requestBody.data、变量占位、responseId和全部前后置断言。
- 关联 `TEST_CASE` 的 method 可能回查为空：执行/导入时会继承 apiDetailId 对应接口的方法，不要因此反复update。场景展开后的 `httpApiCase.method` 应为实际方法。
- 场景用 `test-scenario get <ID> --with-case-detail` 核对步骤数量、顺序、bindId、展开的请求和脚本、运行选项。场景内 `DEBUG_CASE` 不能用单接口 `test-case get` 回查，应读展开场景。
- 官方CLI可能在打印大JSON后立即退出导致截断；使用本技能桥接读取，它同步刷新标准输出并保留CLI原有退出行为。解析失败时只重试读取，不重新创建资源。
- 最后列出同分支的用例和场景，交付项目/分支、资源ID、所需运行时变量名、停止/清理规则及 `testsExecuted=false`。若在AI分支，明确尚未合并；如需交接文件，只放这些非敏感信息。
