# TSE 网关排错手册

## 一、认知类（不是报错，但 90% 的排查跑偏出在这里）

### 「网关返回 400 是网络不通」

**错的，这是最容易被误判的一条。** 报错长这样：

```json
400 {"errorMessage":"domain[81.70.126.212] not found or empty"}
```

**链路其实早就通了** —— 网关把客户端 Host（网关 IP/域名）原样透传给了后端，而后端是 SCF 函数 URL，函数 URL 会校验 Host 必须是自己域名，于是拒收。

**怎么一眼分辨**：看响应头。只要有 `Via: kong/...` 和 `X-Kong-Upstream-Latency`，就说明请求已经打到后端了。此时该去查路由的 `PreserveHost`，**不要去查 VPC 路由表**。

### 「网关 404 是后端挂了」

**大概率不是。** 分两种：

| 情况 | 判断依据 |
|:--|:--|
| 路由根本没匹配上 | 连 `Via: kong` 都没有，或网关直接回 404 |
| 路由匹配了但后端 404 | 有 `Via` + `X-Kong-Upstream-Latency`，说明请求到了后端 |

第二种通常是 **`StripPath=false`**：请求的是 `/demo/ping`，原样转发给后端，后端按 `/ping` 匹配就命中不了。

**两个开关填错的报错完全不同，别搞混：**

| 参数 | 必须 | 填错的后果 |
|:--|:--|:--|
| `PreserveHost` | `false` | 400 `domain[X] not found or empty`（后端是函数 URL 时） |
| `StripPath` | `true` | 404（前缀没剥掉，后端按自己的路径匹配不到） |

### 「网关偶发 504，是后端不稳定」

**先量一下超时再说。** 链路超时是**三段取最小**：

```
网关服务 Timeout（必填，ms） → 后端入口（如函数 URL） → 后端自身执行超时
```

后端是冷启动型（CustomImage / Java）时很容易超默认的 15000ms。**典型症状是网关偶发 504，但后端日志里一切正常** —— 别在后端代码里找问题，先把服务的 `Timeout` 调大。

### 「改完上游后 503，说明配置写错了」

**不是。** 会返回：

```json
{"message": "name resolution failed"}     // HTTP 503
```

这是 Kong 的 DNS 缓存还没过期，**等几秒重试即恢复**。别在这个窗口里去重建服务或改 NetConfig —— 会越改越乱。

### 「Describe 返回 10 条 = 这个网关是空的 / 东西很少」

**错的，这条最危险。** `DescribeCloudNativeAPIGatewayRoutes` / `...Services` 的**默认分页只返回 10 条**，且不报错、不提示。

实测某生产网关真实**路由 176 条、服务 203 个**，默认接口只给 10 条 —— 差 17~20 倍。**凭 10 条的结果去判断环境，会撞名、会误判、会做出错误的操作决策。**

在已有业务的网关上操作前**必须加 `--Limit 200`**（`gateway.py --stage show` 默认就是 200）。

### 「网关关掉公网 = 新加的路由只走内网」

**错的。** 网关的公网开关是**实例级**，不是路由级。实例一旦开了公网（`DescribeCloudNativeAPIGateways` 里 `EnableInternet: true`），在它上面新增的任何路由同样公网可达。

想做到「只有新路由走内网」，只有三条路：整实例关公网（会波及全部现有业务）、路由 `Hosts` 限定（公网用 IP 直连不命中）、新建独立网关。

### 「用 API 能给路由挂 key-auth / jwt 鉴权插件」

**做不到。** 两个证据：

1. 接口清单里 `grep -i plugin` **命中 0 条** —— 没有任何通用插件接口。
2. `ModifyCloudNativeAPIGatewayRoute` 的全量参数逐行核过，**没有 `AuthType`，也没有任何 Plugin 字段**。

**别被接口名骗了**：`CreateCloudNativeAPIGatewayConsumer` / `...SecretKey` / `Describe...ConsumerList` / `...SecretKeyList` 这几个名字看着像「建消费者和密钥」，但在标准版网关上调用会直接返回：

```
OperationDenied: This api is only for aigw
```

它们是**给 AI 网关的模型 API / MCP Server 场景用的**，跟普通路由的 key-auth 无关。

只有约 30 个 Kong 原生插件（key-auth、jwt、basic-auth、acl、bot-detection、request-transformer、proxy-cache…）加上自定义插件包上传，官方文档给的配置路径统一是「登录 Konga 管理控制台 → Add Plugin」。

**务实做法**：需要鉴权时进 Konga 配 key-auth，或在后端函数里自己做 header 校验（一个字段比对比配插件快）。

### 「key-auth 配完了，请求却一直 500 —— 连不带 key 的都 500」

**90% 是 `anonymous` 字段被填了值。** 这是本条最贵的坑：插件配置面板上 `anonymous` 紧挨着 key 相关字段，很容易被当成「填 API Key 的地方」而误填。**它要的是 Consumer 的 UUID，留空才是正常状态。**

Kong 的 key-auth 插件（2.5.1 与 2.8.1 源码一致）逻辑：

```lua
-- do_authentication 内部：无 key 时
if not key or key == "" then
  kong.response.set_header("WWW-Authenticate", _realm)   -- 头先写进响应
  return nil, { status = 401, message = "No API key found in request" }
end
-- do_authentication 内部：key 查不到凭证时
if not credential then
  return nil, { status = 401, message = "Invalid authentication credentials" }
end

-- access 阶段
local ok, err = do_authentication(conf)
if not ok then
  if conf.anonymous then                                   -- ← 只要 anonymous 有值就走这里
    local consumer, err = kong.cache:get(..., kong.client.load_consumer, conf.anonymous, true)
    if err then return error(err) end                      -- ← 抛错 → Kong 返回 500
    set_consumer(consumer)
  else
    return kong.response.error(err.status, err.message, err.headers)  -- ← 正常的 401
  end
end
```

**一旦 `anonymous` 有值，认证失败时就不再返回 401，而是转头去「加载匿名消费者」。填的不是合法 Consumer UUID → 加载失败 → 抛异常 → 500。**

它能把观测到的每个反常现象都对上：

| 现象 | 解释 |
|:--|:--|
| 不带 key → 500，**但带** `WWW-Authenticate` | 先执行了 `set_header`，头已写进响应，之后才崩 |
| 带 key（查不到凭证）→ 500，**不带**该头 | 走的是另一条分支，没经过 `set_header` |
| `X-Kong-Response-Latency` 是 0~3ms，无 `X-Kong-Upstream-Latency` | 请求死在认证阶段，从没转发到上游 |
| 后端（云函数）日志里一条记录都没有 | 同上，网关没把请求发出去 |
| body 恰是 `{"message":"An unexpected error occurred"}` | Kong 插件运行时异常的通用响应体 |

**判据（看这两个组合就够）**：

| 带正确 key | 不带 key | 结论 |
|:--|:--|:--|
| 200 | 500 | 凭证没问题，`anonymous` 还填着 → 清空它 |
| 200 | 401 | 配置正确 |
| 500 | 500 | 凭证也没对上，且 `anonymous` 填着 → 两处一起修 |

**为什么必须清空、而不是「补一个正确的 Consumer UUID」**：这个字段的本意就是「认证失败时放行为匿名消费者」。一旦指向一个**真实存在**的消费者，认证失败就变成**直接放行** —— 等于整个鉴权失效。填错的现在是 fail-closed（500 拦住了），填成合法的反而是 fail-open。所以只能删空，不能「修好」。

> 补充：网关 `EnableCls=False` 时读不到 Kong 的错误堆栈，只能从响应特征反推。上面这套特征矩阵就是没有日志时的定位手段。要开日志得改实例配置。

### 「HTTP 200 且有上游延迟，说明请求已经打到后端了」

**不一定 —— 上游可能根本不是你的后端。** 服务上游是 `Scf`（云函数）类型时，网关是**间接**调用函数的：它先去调 SCF 的云 API。这一步失败时，网关会把 SCF 的 API 错误信封原样当 body 返回，状态码仍是 200，`X-Kong-Upstream-Latency` 也有值。看着链路全通，实际上函数一次都没跑。

```
HTTP/1.1 200 OK
X-Kong-Upstream-Latency: 8
Via: kong/2.5.1

{"Response":{"Error":{"Code":"MissingParameter",
 "Message":"The request is missing the required parameter `Timestamp`."}}}
```

**判据是响应体，不是响应头。** body 里出现 `"Response"` + `"Error"` 就是打到了腾讯云 API，不是你的函数。（`HostIP` 上游指向函数 URL 时不会这样 —— 那条路是 Kong 直接 HTTP 转发，业务错误会是函数自己的响应体。）

**唯一的硬证据是函数日志**：`GetFunctionLogs` 里没有对应记录 = 函数没被触发，问题在网关到函数那一跳。

`Scf` 类型遇到这类报错，优先怀疑网关侧缺少调用 SCF 的 CAM 授权 —— 用云 API 建服务不会顺手把授权补上，要进控制台配。需要立刻可用时，切 `HostIP` 上游指向内网函数 URL 绕开。

### 「实例级白名单能精确控制某条路由」

**不能，而且很危险。** `ModifyNetworkAccessStrategy` 按服务分组 + VIP 生效，**范围覆盖整个网关实例**。共享实例上配上去等于全线断网。且该接口 `NetworkType` 只有 `Open` 可用，`Internal` 官方标注「暂不支持」。

要精细控制用 `CreateOrModifyCloudNativeAPIGatewayIPRestriction` 绑定到自己的路由。

---

## 二、tccli 的报错形态（写脚本必读）

tccli 在**任何失败**时都会先往 stderr 打一段 `usage:` 横幅，真正的异常在横幅**之后**，形如：

```
[TencentCloudSDKException] code:xxx message:yyy
```

中间还夹着 `NotOpenSSLWarning` / `urllib3` 警告。**写脚本解析错误时必须剥掉这两类噪音**，否则截断会把真正的原因挤掉（`gateway.py` 的 `_clean_stderr` / `_sdk_error` 就是为这个加的）。

**另外**：tccli 首次调用某个 action 可能返回空 stdout + `usage:` 横幅，**重试即成功**。别据此判断参数写错。

---

## 三、常见报错

| 报错 / 现象 | 原因 | 处理 |
|:--|:--|:--|
| 400 `domain[X] not found or empty` | 路由 `PreserveHost=true`，客户端 Host 被透传给函数 URL | 改 `PreserveHost=false`。**响应头有 `Via: kong` 就说明链路已通，别查网络** |
| 404（有 `Via` + `X-Kong-Upstream-Latency`） | `StripPath=false`，前缀被原样转发 | 改 `StripPath=true` |
| 404（无 `Via`）`{"message":"no Route matched with those values"}` | 路由不匹配。**方法不对也返回 404，不是 405** | 核对 `Paths` / `Methods` / `Hosts`。要区分「路径错」和「方法错」只能靠逐项比对 `Methods`，网关不区分 |
| 200 但 body 是 `{"Response":{"Error":...}}` | 上游是 `Scf` 类型，网关调 SCF 云 API 那一步失败，函数根本没被触发 | 看 `GetFunctionLogs` 是否为空；优先怀疑网关侧缺 SCF 调用授权，或切 `HostIP` 指向内网函数 URL |
| 502 / 504 | 网关到后端不通 | 检查 ServiceID 绑定；`Scf` 类型核对 `ScfLambdaName` / `ScfType`，`HostIP` 类型核对域名与端口 |
| 偶发 504，后端日志正常 | 超时叠加，最小者先到 | 调大服务的 `Timeout`（单位 ms） |
| 503 `name resolution failed` | 刚改完上游，Kong DNS 缓存 | 等几秒重试 |
| 403 `Your IP address is not allowed` | IP 白名单插件生效，当前 IP 不在名单 | **这是预期行为**，不是故障。确认来源 IP 是否固定 |
| `AuthFailure.SecretIdNotFound` | 凭证缺失 | 让用户自行 `tccli configure` / `tccli auth login`。**不要索要密钥** |
| `AuthFailure.UnauthorizedOperation` | CAM 权限不足 | 需要 tse 侧权限 |
| `ResourceNotFound` | 网关 / 服务 / 路由 ID 不存在 | 核对 ID 与地域。地域不一致会报这个 |
| `InvalidParameterValue` | 参数取值错 | 数组/对象字段要传 JSON 字符串，见 `api.md` |
| `RequestLimitExceeded` | 触发限频（默认 10 次/秒） | 串行调用，加间隔 |
| `function must have function url first` | 网关后端选了云函数但函数 URL 没开 | 去 `scf-release` 开内网函数 URL |
| 本地报 `invalid choice: 'XxxAction'` | 本地 tccli 版本落后 | `pip install -U tccli`；本地 schema 是快照 |

---

## 四、连通性排查顺序

**从 VPC 内 CVM 上**按这个顺序打，逐段定位，某段不通就停在那一段：

```sh
# 1. DNS 能否解析后端域名（仅 HostIP 上游需要）
nslookup <url-id>.in.<region>.tencentscf.com

# 2. 直连后端入口
curl -sv "https://<url-id>.in.<region>.tencentscf.com/" -d '{}'

# 3. 网关内网地址是否可达
ping -c 2 <网关内网IP>
curl -sv "http://<网关内网IP>/<route-path>" -d '{}'

# 4. 网关到后端 —— 看网关侧日志
#    TSE 控制台 -> 网关实例 -> 日志
```

**第 3 步的响应头是关键判据**：

| 头 | 说明 |
|:--|:--|
| `Via: kong/x.y.z` | 请求已进网关 |
| `X-Kong-Upstream-Latency: 74` | 网关**已打到后端**，74ms |
| `X-Scf-Request-Id` | 后端是 SCF 在处理 |

**只要 2 通、3 有 `Via` 且带 `X-Kong-Upstream-Latency`，链路就是完整的** —— 剩下的问题在后端不在网络。

---

## 五、顺序与操作约束

### 5.1 删除必须倒序

```
网关路由 → 网关服务 → （后端资源在各自的 skill 里删）
```

`DeleteCloudNativeAPIGatewayService` 在路由还挂着时会失败。

### 5.2 Modify 是整体覆盖

`ModifyCloudNativeAPIGatewayService` 的 `GatewayId` / `ID` / `Name` / `Protocol` / `Timeout` / `Retries` / `UpstreamType` / `UpstreamInfo` **全是必填**。少传一个字段就可能把原配置抹掉。

`ModifyCloudNativeAPIGatewayRoute` 的 `GatewayId` / `ServiceID` / `RouteID` 三个都必填，`RouteName` 建议一起带上避免被改名。

**改之前先读现配置**（`--stage route-info`），照着改。

### 5.3 `RouteName` 实例级唯一

同一个服务挂第二条路由时名字必须换。`gateway.py --stage show --name X` 的预检会提示。

### 5.4 共享网关六条纪律

1. **先拉全量再动手**：`--Limit 200`，查重名与路径前缀冲突。
2. **不碰实例级配置**：公网开关、IP 访问控制、CORS、限流一改波及全部业务。
3. **只做纯新增**：服务名/路由名带明确前缀（`<name>-svc` / `<name>-route`）。
4. **回收只删自己建的**：按名称精确匹配，绝不按路径前缀批量删。
5. **改错优先 Modify，不要删重建**。
6. **推路由等于把接口暴露到该实例的全部入口**（含公网，如果实例开了公网）。

### 5.5 只读查询被权限系统拦截时

如果 `Describe...` 类调用被审批系统拦截（超时未授权 / 被拒），**不要重试**。如实告知用户哪些信息没拿到，并说明这会影响哪些判断。别用推断填补空白。
