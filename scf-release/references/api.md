# SCF 接口参数速查

所有命令基于 `tccli`，格式：`tccli scf <Action> --param value`。

## 接口表

| Action | 关键参数 | 说明 |
|:--|:--|:--|
| `CreateFunction` | FunctionName / Code / Handler / Runtime / **Type** / VpcConfig / Role / Namespace | `Type=Event` 事件函数，`Type=HTTP` Web 函数 |
| `UpdateFunctionCode` | FunctionName / Handler / Code / **CodeSource** / **Publish** | 只换代码，不动配置。`Publish=TRUE` 可顺带发布版本（默认 FALSE） |
| `UpdateFunctionConfiguration` | FunctionName / Runtime / MemorySize / Timeout / VpcConfig | 改配置；**注意它管的是出站网络** |
| `GetFunction` | FunctionName / Namespace | 查函数详情，探测存在性；`Status` 用于等待 `Active` |
| `ListTriggers` | FunctionName / Namespace | 取函数 URL 地址与 **Qualifier** |
| `CreateTrigger` | FunctionName / TriggerName / **Type=http** / TriggerDesc / Enable / **Qualifier** | **函数 URL 就是这个接口** |
| `UpdateTrigger` | FunctionName / TriggerName / Type / TriggerDesc / Enable / CustomArgument | ⚠ **只支持 timer 和 ckafka**，对 `http` 报 `ResourceNotFound` |
| `DeleteTrigger` | FunctionName / TriggerName / **Type** / Namespace | 删除函数 URL；`Type=http` 必传 |
| `Invoke` | FunctionName / InvocationType / ClientContext / **Qualifier** | 测试函数逻辑，可按版本/别名调 |
| `PublishVersion` | FunctionName / Namespace / **Description** | 把 `$LATEST` 冻结成自增整数版本。**返回 `FunctionVersion`** |
| `ListVersionByFunction` | FunctionName / Namespace / Offset / Limit / Order / OrderBy | 列版本；`Versions[].Description` 里存 semver |
| `CreateAlias` / `UpdateAlias` | FunctionName / Name / **FunctionVersion** / RoutingConfig / Description | 别名指向版本；灰度靠 `RoutingConfig.AdditionalVersionWeights` |
| `GetAlias` / `ListAliases` | FunctionName / Name | 查别名 |
| `DeleteAlias` | FunctionName / Name | 删别名（删函数前需先摘） |
| `DeleteFunctionVersion` | FunctionName / FunctionVersion | 删单个历史版本 |
| `DeleteFunction` | FunctionName | 删函数 |

## FunctionUrl 的 TriggerDesc

```json
{
  "AuthType": "NONE",
  "NetConfig": { "EnableIntranet": true, "EnableExtranet": false },
  "CorsConfig": {
    "Enable": true,
    "Origins": ["*"],
    "Headers": ["content-type"],
    "Methods": ["POST", "PATCH"],
    "ExposeHeaders": ["*"],
    "MaxAge": 10,
    "Credentials": true
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|:--|:--|:--|:--|
| AuthType | String | 是 | `CAM` 需鉴权；`NONE` 免鉴权 |
| NetConfig | Object | 是 | 网络访问配置 |
| NetConfig.EnableIntranet | Bool | 是 | 开启内网访问 |
| NetConfig.EnableExtranet | Bool | 是 | 开启公网访问 |
| CorsConfig | Object | 否 | 跨域配置 |

> **只开内网 = `EnableIntranet: true` + `EnableExtranet: false`。**

## 内网端点格式

```
https://<url-id>.in.<region>.tencentscf.com     内网
https://<url-id>.<region>.tencentscf.com        公网
```

`<url-id>` 由 SCF 生成，**重建触发器会换掉它**（见 `troubleshooting.md`）。

## Code 结构

| 字段 | 说明 |
|:--|:--|
| ZipFile | zip 内容的 base64 |
| CosBucketName | COS 桶名（不含 -appid） |
| CosObjectName | COS 对象路径，以 / 开头 |
| CosBucketRegion | 仅北京需传 `ap-beijing` / `ap-beijing-1` |
| DemoId | 用模板创建时传 |

不能同时指定 Cos / ZipFile / DemoId。

**大小上限有两个口径，别混：**

| 参数 | 上限 |
|:--|--:|
| `UpdateFunctionCode` 顶层 `ZipFile` | 20 MB |
| `Code.ZipFile`（推荐） | 50 MB |
| 解压后（代码 + Layer）总大小 | 500 MB |

`CodeSource` 取 `ZipFile` / `Cos` / `Inline`；走 COS 时传 `CodeSource=Cos` + 三个 `Cos*` 参数。

## 版本与别名语义

| 概念 | 含义 |
|:--|:--|
| `$LATEST` | 可被任意次 `UpdateFunctionCode` 覆盖，**没有版本号** |
| 数字版本 `1,2,3…` | `PublishVersion` 冻结产生，**不可变、不可指定编号** |
| 别名 | 指向一个数字版本，可另配一个附加版本 + 权重做灰度 |
| `$DEFAULT` | 内置别名，初始指向 `$LATEST` |

**上传 / 发布 / 切流量是三个独立动作**：`UpdateFunctionCode`（改 `$LATEST`）→
`PublishVersion`（冻结版本）→ `UpdateAlias`（切流量）。前两步都不改变线上流量。

semver 无法写进版本号，只能写进 `PublishVersion` 的 `Description` 做映射。

触发器 `Qualifier` 决定线上跟随谁：`$LATEST` = 上传即上线；别名 = 上传不动线上。

## Runtime 可选值

`Python2.7` `Python3.6` `Python3.7` `Python3.9` `Python3.10` `Nodejs16.13` `Nodejs18.15` `Php7.4` `Go1` `Java8` `CustomRuntime`

**没有 Python3.11+ / 3.13。**

## 函数 URL 调用时 event 的字段

```json
{
  "body": "{\"test\":\"hello world\"}",
  "headers": { "content-type": "application/json", "x-scf-remote-addr": "1.2.3.4" },
  "httpMethod": "POST",
  "path": "/",
  "queryString": { "a": "1" }
}
```

无 `requestContext` / `pathParameters` / `headerParameters` / `isBase64Encoded`。

## 函数应返回的结构

```json
{
  "isBase64Encoded": false,
  "statusCode": 200,
  "headers": { "Content-Type": "application/json" },
  "body": "{\"ok\":true}"
}
```

若不返回 `statusCode`（只返回合法 JSON），平台按 200 + `application/json` 处理。

## 依赖打包（按目标运行时装 wheel）

```sh
pip install \
  --python-version 3.10 \
  --only-binary=:all: \
  --platform manylinux2014_x86_64 \
  --target ./pkg \
  <你的依赖>
```

- 用 `--python-version` 对齐 SCF 运行时，**不是本地解释器版本**
- 用 `--only-binary=:all:` 避免源码编译出不兼容的 .so
- `--platform` 选 `manylinux2014_x86_64`（SCF 标准架构）
- 装完把 `pkg/` 整个作为 `--src` 传进 `deploy.py`

---

## 文档检索入口（接口不确定时先查，别猜）

```sh
# 找服务名
curl -s https://cloudcache.tencentcs.com/capi/refs/services.md | grep 云函数

# 列接口
curl -s https://cloudcache.tencentcs.com/capi/refs/service/scf/actions.md | grep -i trigger

# 看接口参数
curl -s https://cloudcache.tencentcs.com/capi/refs/service/scf/action/CreateTrigger.md

# 看数据结构
curl -s https://cloudcache.tencentcs.com/capi/refs/service/scf/model/Code.md

# 看最佳实践
curl -s https://cloudcache.tencentcs.com/capi/refs/service/scf/practice/practice-5.md
```

本地 tccli 是版本快照，**以在线文档为准**。函数 URL 这类新能力，本地 schema 里可能完全没有。
