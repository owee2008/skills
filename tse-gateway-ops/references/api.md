# TSE 云原生网关接口参数速查

所有命令基于 `tccli`，格式：`tccli tse <Action> --param value`。

## 接口表

| Action | 关键参数 |
|:--|:--|
| `CreateCloudNativeAPIGatewayService` | GatewayId / Name / Protocol / Timeout / Retries / **UpstreamType** / UpstreamInfo |
| `ModifyCloudNativeAPIGatewayService` | GatewayId / **ID** / Name / Protocol / Timeout / Retries / UpstreamType / UpstreamInfo（**全是必填**，整体覆盖不是局部改） |
| `CreateCloudNativeAPIGatewayRoute` | GatewayId / **ServiceID** / RouteName / Methods / Paths / Hosts / Protocols / StripPath / PreserveHost |
| `ModifyCloudNativeAPIGatewayRoute` | GatewayId / ServiceID / **RouteID** / RouteName / Methods / Paths / Protocols / PreserveHost / StripPath / ForceHttps / HttpsRedirectStatusCode / DestinationPorts / Headers / RequestBuffering / ResponseBuffering / RegexPriority / QueryStringParameters |
| `DescribeCloudNativeAPIGateway` | GatewayId（实例详情，含 `EnableInternet` / `VpcId`） |
| `DescribeCloudNativeAPIGatewayServices` | GatewayId / **Limit**（默认只给 10 条） |
| `DescribeCloudNativeAPIGatewayRoutes` | GatewayId / **Limit**（默认只给 10 条） |
| `DeleteCloudNativeAPIGatewayRoute` | GatewayId / ServiceID / RouteName |
| `DeleteCloudNativeAPIGatewayService` | GatewayId / ServiceID |
| `DescribeCloudNativeAPIGatewayPorts` | GatewayId（端口配置，通常 HTTP 80 / HTTPS 443） |
| `CreateCloudNativeAPIGatewayPublicNetwork` | 创建公网配置（**不调 = 仅内网**） |
| `DeleteCloudNativeAPIGatewayPublicNetwork` | 收回公网（实例级） |

> 查公网现状**不要用 `DescribePublicNetwork`**：它不是 tse 的独立 action，tccli 会把它解析到别的服务并报 `the following arguments are required: --GroupId, --NetworkId`，看起来像"没配"其实是打错接口了。改用 `DescribeCloudNativeAPIGateway`，读 `EnableInternet`（布尔）与 `PublicIpAddresses`（公网 IP 列表，未开公网时为空或缺席）。
| `ModifyNetworkAccessStrategy` | 实例级白/黑名单。`NetworkType` 只有 `Open` 可用，`Internal` 官方标注「暂不支持」 |
| `CreateOrModifyCloudNativeAPIGatewayIPRestriction` | GatewayId / **SourceType**(route\|service) / **SourceId** / Enabled / **RestrictionType**(whiteList\|blackList) / AddressList |
| `DescribeCloudNativeAPIGatewayIPRestriction` | GatewayId / SourceType / SourceId |
| `DeleteCloudNativeAPIGatewayIPRestriction` | 同上 |
| `CreateCloudNativeAPIGatewayRouteRateLimit` / `...ServiceRateLimit` | `LimitDetail.LimitBy`(ip\|service\|consumer\|credential\|path\|header) / QpsThresholds / `Policy`(local\|redis\|external_redis) |
| `CreateOrModifyCloudNativeAPIGatewayCORS` | Origins / Headers / Methods / Credentials / MaxAge |
| `CreateCloudNativeAPIGatewayCertificate` | `CertUsage`(SERVER\|CLIENT) / `CertType`(SVR\|CA) |
| `OpenWafProtection` / `CloseWafProtection` | GatewayId / `Type`(Global\|Service\|Route) |
| `CreateWafDomains` | 绑 WAF 域名 |
| `CreateCloudNativeAPIGatewayConsumer` / `...ConsumerGroup` | Priority / Status(Enable\|Disable) |
| `CreateCloudNativeAPIGatewaySecretKey` | `SecretType`(ApiKey\|Basic\|Hmac\|OAuth2\|JWT) |
| `CreateCloudNativeAPIGatewayCanaryRule` | 按服务配灰度规则 |
| `DescribeCloudNativeAPIGatewayConfig` | 网关配置总览 |
| `CreateNativeGatewayServiceSource` | 服务来源（K8s / 注册中心场景） |

> ⚠ **没有通用插件接口。** 接口清单里 `grep -i plugin` 命中 0 条。key-auth / jwt / basic-auth / acl / 自定义插件等只能进 Konga 控制台配。
> ⚠ `ModifyCloudNativeAPIGatewayRoute` 的全量参数里**没有 `AuthType`、没有任何 Plugin 字段** —— 「用 API 给路由挂鉴权插件」这条路是断的。

## UpstreamType 取值

`Kubernetes` / `Registry` / `IPList` / `HostIP` / `Scf`

接云函数用最后两个：
- **`Scf`** —— 网关经 SCF 内网接口调用，不经过函数 URL
- **`HostIP`** —— 指向域名或 IP，接函数时填内网函数 URL 的域名

## UpstreamInfo（KongUpstreamInfo）字段

| 字段 | 说明 |
|:--|:--|
| Host / Port | `HostIP` 类型用，指向域名或 IP |
| ScfType | SCF 函数类型，**必须与实际一致**：事件函数填 `Event`，Web 函数填 `HTTP` |
| ScfNamespace | SCF 命名空间 |
| ScfLambdaName | SCF 函数名 |
| ScfLambdaQualifier | SCF 函数版本或别名，如 `$LATEST`、`prod` |
| SourceID / SourceType | 服务来源（K8s / 注册中心场景） |
| Targets | `IPList` 类型的节点列表 |
| SlowStart | 冷启动时间（秒） |
| Algorithm | `round-robin`（默认）/ `least-connections` |

## Route 参数要点

- `Paths`：路由路径数组，如 `["/demo"]`
- `Methods`：`GET` `POST` `PUT` `DELETE` `HEAD` `OPTIONS` `PATCH` `ANY` 等
- `Hosts`：不填 = 匹配任意 Host，内网直接打网关 IP 即可。**但公网入口同样能打到**
- `StripPath`：转发时是否剥掉前缀路径。**后端按自身路径匹配时必须 `true`**
- `PreserveHost`：转发时是否保留原 Host。**后端是函数 URL 时必须 `false`**
- `ForceHttps` / `HttpsRedirectStatusCode`：强制跳转 HTTPS

**参数值是数组或对象的**（`Methods` / `Paths` / `Protocols` / `UpstreamInfo`）用 tccli 时要传 JSON 字符串：

```sh
--Methods '["GET","POST"]' --Paths '["/demo"]' --Protocols '["http","https"]'
--UpstreamInfo '{"Host":"x.in.ap-beijing.tencentscf.com","Port":80}'
```

## 支持地域

`ap-guangzhou` `ap-shanghai` `ap-beijing` `ap-chengdu` `ap-nanjing` `ap-hongkong` `ap-singapore` `ap-tokyo` `ap-seoul` `ap-bangkok` `ap-jakarta` `na-ashburn` `na-siliconvalley` `eu-frankfurt` `ap-shanghai-fsi` `ap-shenzhen-fsi`

---

## 文档检索入口（接口不确定时先查，别猜）

```sh
# 列全部接口（找有没有某个能力，这是最快的一步）
curl -s https://cloudcache.tencentcs.com/capi/refs/service/tse/actions.md | grep -oE "^[A-Za-z]+" | sort -u

# 找安全/插件相关
curl -s https://cloudcache.tencentcs.com/capi/refs/service/tse/actions.md | grep -inE "plugin|auth|limit|acl|waf|cert"

# 看接口参数
curl -s https://cloudcache.tencentcs.com/capi/refs/service/tse/action/CreateCloudNativeAPIGatewayRoute.md

# 看数据结构
curl -s https://cloudcache.tencentcs.com/capi/refs/service/tse/model/KongUpstreamInfo.md

# 看最佳实践（注意 practice-32 有复制粘贴错误：X-TC-Action 写成了限流接口名）
curl -s https://cloudcache.tencentcs.com/capi/refs/service/tse/practice/practice-19.md
```

本地 tccli 是版本快照，**以在线文档为准**。
