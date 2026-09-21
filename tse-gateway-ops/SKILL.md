---
name: tse-gateway-ops
display_name: TSE 云原生网关运维（服务 / 路由 / 上游）
description: 腾讯云 TSE 云原生网关的服务、路由与上游配置 —— 新建服务与路由、切换上游地址、盘点现有配置与冲突预检、共享生产网关的操作纪律、内网访问控制与 IP 白名单。当用户提到「云原生网关」「TSE 网关」「网关加路由」「网关接云函数」「网关 404/400/502」「网关白名单」时加载。函数本身的部署与版本管理见 scf-release。
agent_created: true
version: 1.2.0
tags: [tencentcloud, tse, gateway, kong, routing, upstream, access-control, intranet]
keywords: [云原生网关, TSE, 网关路由, CreateCloudNativeAPIGatewayRoute, 服务上游, UpstreamType, HostIP, Scf, PreserveHost, StripPath, 分页, Limit, IP白名单, IPRestriction, 访问控制, 共享网关]
---

# TSE 云原生网关运维

管理云原生网关上的**服务**、**路由**与**上游**。与后端类型无关 —— 上游可以是 SCF 云函数、CVM、容器或 IP 列表。

## 适用场景

- 「在网关上加一条路由」「后端接云函数」
- 「网关返回 400 / 404 / 502 怎么办」
- 「函数 URL 变了，网关上游要跟着改」
- 「网关怎么配 IP 白名单 / 限流」
- 「这个网关上有多少东西，加东西会不会撞名」

## 反面场景（不要用本 skill）

- 只是要部署函数、开函数 URL、发版本 → 那是 `scf-release`
- 后端不是网关而是直接暴露 CVM → 用 CLB，不是网关

## 职责边界

| | scf-release | 本 skill（tse-gateway-ops） |
|:--|:--|:--|
| 管什么 | 函数、函数 URL、版本、别名 | 网关服务、路由、上游、访问控制 |
| 脚本 | `deploy.py` | `gateway.py` |

**唯一的交界处：网关服务的上游可以指向函数。** 两种接法（选 `Scf` 类型 / 指向内网函数 URL）都在本 skill 配置；函数侧的准备（函数存在、内网 URL 已开）属 `scf-release`。

---

## 一、先钉死这 11 条事实（做错其中之一必返工）

1. **网关默认不开公网 —— 公网是显式创建出来的。** 不调 `CreateCloudNativeAPIGatewayPublicNetwork`，网关就只在内网可达。收回用 `DeleteCloudNativeAPIGatewayPublicNetwork`。校验用 `DescribeCloudNativeAPIGateway` 读 `EnableInternet` 与 `PublicIpAddresses`（`DescribePublicNetwork` 不是 tse 的独立 action，打它会报缺 `--GroupId`，别拿它当判据）。
2. **公网开关是实例级，不是路由级。** 实例一旦开了公网（`DescribeCloudNativeAPIGateways` 里 `EnableInternet: true`），在它上面新增的**任何路由同样公网可达** —— 「只让新路由走内网」在共享实例上做不到。只有三条路：整实例关公网（会波及全部现有业务）、路由 `Hosts` 限定（公网用 IP 直连不命中）、新建独立网关。
3. **`DescribeCloudNativeAPIGatewayRoutes` / `...Services` 默认只返回 10 条，且不报错、不提示。** 实测某生产网关真实**路由 176 条、服务 203 个**，默认接口只给 10 条 —— 差 17~20 倍。在已有业务的网关上操作前**必须加 `--Limit 200` 拉全量**，否则会误判环境、还可能撞名。
4. **路由的 `PreserveHost` 必须 `false`。** 填 `true` 会把客户端 Host（网关 IP/域名）透传给后端。**当后端是 SCF 函数 URL 时**，函数 URL 会校验 Host 必须是自己域名，直接返回 `400 {"errorMessage":"domain[X] not found or empty"}`。**链路其实是通的**，别去查网络。
5. **路由的 `StripPath` 通常必须 `true`。** 填 `false` 会把 `/demo/ping` 原样转发，后端按 `/ping` 匹配就命中不了 → 404。仅当后端自己就认识带前缀的路径时才关。（5 和 4 报错现象完全不同，别搞混。）
6. **服务的 `Retries` 必须 `0`。** 腾讯云官方创建服务的示例给的是 `Retries: 3`。照抄到**非幂等**后端上（下单、发消息、写库），网关重试 = 重复执行，这是唯一会直接造成生产事故的参数。
7. **超时是叠加的，失败现象是「偶发 504」。** 链路三段取最小：网关服务 `Timeout`（**必填，单位 ms**）→ 后端入口（如函数 URL）→ 后端自身执行超时。后端是冷启动型服务（CustomImage、Java）时很容易超默认值。**表现是网关偶发 504，但你去翻后端日志会发现一切正常** —— 别在那儿浪费时间。
8. **`ModifyCloudNativeAPIGatewayService` / `...Route` 都是整体覆盖，不是局部改。** 例：`Modify...Service` 的 `GatewayId` / `ID` / `Name` / `Protocol` / `Timeout` / `Retries` / `UpstreamType` / `UpstreamInfo` **全是必填**；`Modify...Route` 的 `GatewayId` / `ServiceID` / `RouteID` 三个都必填，且 `RouteName` 建议一起带上避免被改名。
9. **`RouteName` 是实例级唯一。** 给同一个服务挂第二条路由时，路由名必须换（`<name>-route` 会撞）。
10. **改完服务上游后，网关会短暂 503 `{"message":"name resolution failed"}`。** 这是 Kong 的 DNS 缓存还没过期，**等几秒重试即恢复，不是配置错**。别在这个窗口里去重建服务或改 NetConfig。
11. **TSE 没有通用的插件 API —— key-auth 只能在 Konga 里配。** 接口清单里 `grep -i plugin` 命中 0 条。只有少数几个插件被单独立了 API（IP 访问控制、限流、CORS、WAF、证书），**key-auth / jwt / basic-auth / acl / request-transformer 等约 30 个 Kong 原生插件以及自定义插件，官方文档给的配置路径统一是「登录 Konga 管理控制台 → Add Plugin」，没有 API 版本**。而且 `ModifyCloudNativeAPIGatewayRoute` 的全量参数里**没有 `AuthType`、也没有任何 Plugin 字段** —— 「用 API 给路由挂 key-auth」这条路是断的。
    - 名字里带 `Consumer` / `SecretKey` 的那几个云 API（`CreateCloudNativeAPIGatewayConsumer` / `...SecretKey` / `Describe...ConsumerList` / `...SecretKeyList`）**只对 AI 网关开放**：在标准版网关上调用会直接报 `OperationDenied: This api is only for aigw`。别被接口名误导去照着它写脚本。
    - Konga 里配 key-auth 时，**`anonymous` 字段必须留空**。填任何值（哪怕填成 API Key）都会让「认证失败」分支从 401 变成 500。详见 `references/troubleshooting.md`。
    - 需要鉴权时，务实做法是进控制台配 key-auth；在共享网关上不想开公网、又不想让请求在网关侧被拦错，也可以在后端函数里自己校验 header。

---

## 二、执行流程

### Step 0 · 盘点现状（动手前必做）

```sh
python3 scripts/gateway.py --stage show \
  --region "$REGION" --gateway-id "$GATEWAY_ID"
```

输出包含：实例信息与**公网开关状态**、服务总数与列表、路由总数与列表，以及**冲突预检**（你要用的服务名 / 路由名 / 路径是否已被占用）。

带过滤与预检：

```sh
python3 scripts/gateway.py --stage show \
  --region "$REGION" --gateway-id "$GATEWAY_ID" \
  --grep demo-fn --name demo-fn --route-path /demo
```

> `--limit` 默认 200。**不要改成 10 然后相信输出** —— 那就是事实 3 的陷阱。

### Step 1 · 建服务

**路线 A —— 后端选 `Scf`（配置最干净，但**先探一次**再决定）**

网关经 SCF 内网接口调用函数，**完全不经过函数 URL**，不受 URL 开关、域名解析影响。

⚠ **这条路依赖网关侧持有调用 SCF 的 CAM 授权，而创建服务的云 API 不会顺手把授权建出来。** 未授权时的表现非常反直觉：网关返回 HTTP 200，body 是腾讯云 API 错误信封而不是函数响应，`X-Kong-Upstream-Latency` 也有值（看起来"打通了"），而函数日志里**一条记录都没有**：

```json
{"Response":{"Error":{"Code":"MissingParameter",
 "Message":"The request is missing the required parameter `Timestamp`."}}}
```

这是签名层报缺 `Timestamp`，指向 CAM 授权缺失。**先按下面的命令建服务并打一次请求**，看响应体是不是函数真正的返回；是 API 错误信封就补授权，或者直接落路线 B。

```sh
python3 scripts/gateway.py --stage service --region "$REGION" \
  --gateway-id "$GATEWAY_ID" --name demo-fn \
  --upstream scf --function-name demo-fn --function-type Event \
  --namespace default
```

**路线 B —— 后端用内网函数 URL**

```sh
python3 scripts/gateway.py --stage service --region "$REGION" \
  --gateway-id "$GATEWAY_ID" --name demo-fn \
  --upstream url \
  --intranet-url 'https://1318516741-xxxx.in.ap-beijing.tencentscf.com' \
  --intranet-port 80 --service-protocol http
```

两条路线的差别：

| | 路线 A（Scf） | 路线 B（内网 URL） |
|:--|:--|:--|
| 依赖函数 URL | 不依赖 | 依赖，且必须开内网 |
| 域名解析 | 不需要 | 网关需能解析 `*.in.<region>.tencentscf.com` |
| 配置量 | 最少 | 多一步取 URL |
| 换函数版本 | 改 `ScfLambdaQualifier` 一个字段 | 函数 URL 变了就得改上游（事实 11 的连锁反应） |
| 请求语义 | 网关转 event | HTTP 原样转发到 URL 端点 |

拿不准就先试 A，A 通不了再落 B。

**⚠ `--function-type` 必须与函数实际类型一致**（`Event` / `HTTP`）。填错不会立刻报错，而是请求打进去后才出问题。

### Step 2 · 建路由

```sh
python3 scripts/gateway.py --stage route --region "$REGION" \
  --gateway-id "$GATEWAY_ID" --name demo-fn \
  --service-id "<Step 1 返回的 ServiceID>" \
  --route-path /demo --strip-path
```

脚本固定按 `PreserveHost=false` 创建（事实 4）。

**路径语义要对齐**：`--route-path /demo` + `--strip-path` 意味着 `/demo/ping` 会被剥成 `/ping` 再喂给后端。后端原生路径是什么，路由前缀就要配成它的外衣。

路由的**域名不填**（`Hosts` 省略）表示匹配任意 Host，内网直接打网关 IP 即可。但这也意味着**公网入口同样能打到**这条路由（事实 2）。

### Step 3 · 建错的路由不用删，直接改

```sh
# 先取 RouteID（必须带 Limit）
python3 scripts/gateway.py --stage route-info \
  --region "$REGION" --gateway-id "$GATEWAY_ID" --name demo-fn

# 再改（三个 ID 都必填，且是整体覆盖）
tccli tse ModifyCloudNativeAPIGatewayRoute --region "$REGION" \
  --GatewayId "$GATEWAY_ID" --ServiceID "<ServiceID>" --RouteID "<RouteID>" \
  --RouteName "demo-fn-route" --Methods '["GET","POST"]' \
  --Paths '["/demo"]' --Protocols '["http","https"]' \
  --PreserveHost false --StripPath true
```

### Step 4 · 切换服务上游

典型触发场景：**函数 URL 的触发器被重建，内网 URL 的 id 变了，旧地址立即失效。**
（这是 `scf-release` 侧 `--stage qualifier` 的连锁后果，去做那步之前先看这里。）

```sh
python3 scripts/gateway.py --stage upstream --region "$REGION" \
  --gateway-id "$GATEWAY_ID" --service-id "<ServiceID>" --name demo-fn \
  --intranet-url 'https://<新 url-id>.in.<region>.tencentscf.com'
```

改完头几秒的 503 是正常现象（事实 10）。

### Step 5 · 验证

```sh
# 内网入口（必须在 VPC 内 CVM 上）
curl -sv "http://<网关内网IP>/demo/ping"

# 公网入口（实例已开公网时，本地开发机也能测）
curl -sv "http://<网关公网IP>/demo/ping"
```

**看响应头就能判断链路走到哪一段**：

| 响应头 | 含义 |
|:--|:--|
| `Via: kong/...` | 请求已进入网关 |
| `X-Kong-Upstream-Latency: 74` | 网关**已成功打到后端**，延迟 74ms |
| `X-Scf-Request-Id` | 后端确实是 SCF 在处理 |

**只要看到 `Via` + `X-Kong-Upstream-Latency`，就说明后端已被打到 —— 此时若返回 400/500，问题在后端不在网络，别去查 VPC 路由表。**

判定表：

| 现象 | 结论 | 下一步 |
|:--|:--|:--|
| 网关返回 400 `domain[X] not found or empty` | 路由 `PreserveHost=true`，客户端 Host 被透传给函数 URL | 改成 `false`（事实 4） |
| 网关返回 404 | 路由不匹配 | 核对 `Paths` / `Methods`；确认 `StripPath` |
| 路由确认匹配但仍 404 | `StripPath=false`，前缀没剥掉 | 改成 `true`（事实 5） |
| 网关返回 502 / 504 | 网关到后端不通 | 核对 ServiceID 绑定；路线 A 查 `ScfLambdaName`，路线 B 查内网 URL 与域名解析 |
| 网关偶发 504，后端日志正常 | 超时叠加，最小者先到 | 调大服务的 `Timeout`（事实 7） |
| 503 `name resolution failed` | 刚改完上游，Kong DNS 缓存 | 等几秒重试（事实 10） |

### Step 6 · 回收

```sh
# 顺序：路由 -> 服务（后端资源的删除在 scf-release）
tccli tse DeleteCloudNativeAPIGatewayRoute --region "$REGION" \
  --GatewayId "$GATEWAY_ID" --ServiceID "<ServiceID>" --RouteName "demo-fn-route"

tccli tse DeleteCloudNativeAPIGatewayService --region "$REGION" \
  --GatewayId "$GATEWAY_ID" --ServiceID "<ServiceID>"
```

`DeleteCloudNativeAPIGatewayService` 在路由还挂着时会失败。**别按路径前缀批量删** —— 共享网关上会误伤别人的路由。

---

## 三、访问控制与安全

### 3.1 真正的「只开内网」

**只有一招：`DeleteCloudNativeAPIGatewayPublicNetwork`。** 但它是**实例级**的 —— 如果网关上有别人的生产路由，动它等于全线断网。要做只能在新建独立实例上做。

### 3.2 IP 白名单（绑定到自己的路由或服务）

```sh
tccli tse CreateOrModifyCloudNativeAPIGatewayIPRestriction --region "$REGION" \
  --GatewayId "$GATEWAY_ID" \
  --SourceType route \
  --SourceId "<RouteID>" \
  --Enabled true \
  --RestrictionType whiteList \
  --AddressList '["203.0.113.10/32"]'
```

- `SourceType=route|service`：选 `service` 则对该服务的所有路由生效。
- **改之前先读一次现状**：`DescribeCloudNativeAPIGatewayIPRestriction --SourceType route --SourceId <ID>`。
- **回滚**：`--Enabled false` 关掉保留配置；`DeleteCloudNativeAPIGatewayIPRestriction` 彻底删除。
- 验证：白名单内 IP → 200；名单外 → **403 + `{"message":"Your IP address is not allowed"}`**（Kong `ip-restriction` 的标准响应）。看到 403 就是插件生效了，别再往 VPC 路由上找原因。

**五个坑：**

| 坑 | 说明 |
|:--|:--|
| 来源 IP ≠ 你以为的客户端 IP | 若调用方经过代理、LB 或 NAT，网关看到的可能是出口 IP。**先确认它是固定 IP**，会变的话白名单会随机抽风 |
| 内网调用方也会被拦 | 插件挂在路由上**不区分入口**，VPC 内 CVM 或别的服务的 IP/CIDR 必须一起进白名单 |
| 前面挂 WAF/CDN 会改变来源 IP | 那一层之后网关看到的可能是回源地址，白名单得跟着换 |
| API 版白名单是单模式 | `RestrictionType` 只能取 `whiteList` 或 `blackList` 之一，不能 allow + deny 混配。控制台的 Kong 插件界面才有双列表，且官方明确同一 IP 同时命中时**按拒绝处理** |
| 别动实例级 | `ModifyNetworkAccessStrategy` 是按服务分组 + VIP 生效、范围覆盖整个实例。且该接口 `NetworkType` 只有 `Open` 可用，`Internal` 官方标注「暂不支持」 |

> ⚠ **本节参数取自官方文档与接口清单核对，尚未实跑验证。** 落地前先按 Step 0 盘点，并在自己的路由上小范围试一次。

### 3.3 其它可以走 API 的安全能力

| 能力 | 接口 | 备注 |
|:--|:--|:--|
| 限流（路由级 / 服务级） | `CreateCloudNativeAPIGatewayRouteRateLimit` / `...ServiceRateLimit` | `LimitBy` 支持 `ip/service/consumer/credential/path/header`；`Policy=local\|redis\|external_redis` |
| CORS | `CreateOrModifyCloudNativeAPIGatewayCORS` | |
| 强制 HTTPS | `ModifyCloudNativeAPIGatewayRoute` 的 `ForceHttps` / `HttpsRedirectStatusCode` | |
| TLS 证书 | `CreateCloudNativeAPIGatewayCertificate` | `CertUsage=SERVER\|CLIENT` |
| WAF | `OpenWafProtection` / `CloseWafProtection` / `CreateWafDomains` | `Type=Global\|Service\|Route` |
| 消费者 / 密钥 | `CreateCloudNativeAPIGatewayConsumer` / `...SecretKey` | **标准版网关调不通** —— 实测报 `OperationDenied: This api is only for aigw`，只对 AI 网关开放。key-auth 请走 Konga，见事实 11 |

> ⚠ 同样**未实跑验证**。另外注意官方最佳实践 `practice-32` 里 `X-TC-Action` 被写错成了限流接口名，照着它手搓 HTTP 请求会打错接口（用 tccli 不受影响）。

---

## 四、共享生产网关操作纪律

网关常是**多人共用**的（实测存在 **176 条路由、203 个服务**的实例，上面跑着日志系统、工单识别、人员管理等业务）。在上面做增量必须守这六条：

1. **先拉全量再动手**：`--Limit 200` 把路由和服务都拉下来，查重名、查路径前缀冲突。默认的 10 条不够看。
2. **不碰实例级配置**：公网开关、IP 访问控制、CORS、限流都是实例级，一改波及所有业务。要改必须先找业务方确认。
3. **只做纯新增**：新增服务 + 新增路由，命名带明确前缀（`<name>-svc` / `<name>-route`），便于日后精确回收。（`--stage show --name X` 会做冲突预检。）
4. **回收只删自己建的**：按名称精确匹配，绝不按路径前缀批量删。
5. **改错优先 Modify，不要删重建**：删了重建会换 ID，可能影响别处引用。
6. **在共享网关上推路由，等于把接口暴露到该实例的全部入口**（含公网，如果实例开了公网）。推之前想清楚这是不是你要的。

---

## 五、安全红线

- **不向用户索要 SecretId / SecretKey**，不执行任何会打印凭证的命令（尤其 `tccli configure list`）。
- 创建/删除类操作用户确认后再执行。**在共享实例上删除路由/服务前，必须先确认它是不是自己建的。**
- 只读查询若被权限系统拦截（审批超时/被拒），**不要重试**，如实告知用户哪些信息没拿到。

## 六、参数速查

接口字段见 `references/api.md`，报错处理见 `references/troubleshooting.md`。
