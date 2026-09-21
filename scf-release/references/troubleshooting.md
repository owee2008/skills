# SCF 排错手册

## 一、认知类（不是报错，但 90% 的返工出在这里）

### 「函数 URL 只有 Web 函数能用」

**错的。** 函数 URL 与触发器同级，事件函数和 Web 函数都支持。区别只在事件函数收到的是 event 结构，Web 函数收到的是原始 HTTP 请求。

### 「SCF 网络配置选『仅内网访问』就等于外部调不进来」

**错的。** SCF 控制台的网络配置管的是**函数出站** —— 函数运行时能不能访问公网、能不能访问 VPC 内资源。它不控制谁能调用函数。

要让外部调不进来，改的是**函数 URL 的 `NetConfig.EnableExtranet = false`**。

### 「本地 curl 内网 URL 超时，说明部署错了」

**错的。** 本地开发机走公网，本来就到不了内网端点。必须从同 VPC 内 CVM 测。别在这里排查代码。

### 「更新完代码就等于上线了」

**分情况，这是最容易搞错的一条。**

- 触发器（函数 URL）`Qualifier` 是 **`$LATEST`**（默认）→ **是的，`UpdateFunctionCode` 一返回，线上立刻是新代码**，没有版本号、没留档、没法秒回滚。
- 触发器 `Qualifier` 是**别名**（如 `prod`）→ 上传只动 `$LATEST`，**线上纹丝不动**，切流量靠 `UpdateAlias`。

实测证据：同一个函数，`$LATEST` 已更新到 0.4.0，线上打过去仍然是 0.3.0，直到把别名指过去才变 0.4.0。

所以「能不能把上传和部署拆成两步」的答案是：**API 层面可以**（`UpdateFunctionCode` / `PublishVersion` / `UpdateAlias` 三个独立接口），**但前提是触发器别绑 `$LATEST`**。

### 「用 UpdateTrigger 改函数 URL 的配置」

**对 http 触发器不成立。** 官方文档原话：*"注意：目前只支持 timer 触发器和 ckafka 触发器更新！"* 实测对 `Type=http` 直接报 `ResourceNotFound`，即使请求里带了 `Qualifier` 参数也不会生效。

**http 触发器（函数 URL）只能删除 + 重建。** 代价是**内网 URL 的 id 会变**（实测 `5o8f5pjbdq` → `k4zvlwjzsg`），旧 URL 立即失效 —— 任何指向它的**网关服务**上游必须同步改，否则网关 503（改上游属 `tse-gateway-ops`）。

推论：**绑定要在第一次就绑到别名**。绑死数字版本的话，以后每次换版本都得再重建一次触发器。

### 「tccli 报 usage 就是参数写错了」

**不一定，先重试一次再改代码。** tccli 首次调用某个 action 时可能返回空 stdout + `usage:` 横幅，重试即成功。实测 `PublishVersion`、`GetAlias`、`CreateAlias` 的**首次调用**都踩到过这个。

---

## 二、tccli 的报错形态（写脚本必读）

tccli 在**任何失败**时都会先往 stderr 打一段 `usage:` 横幅，真正的异常在横幅**之后**，形如：

```
[TencentCloudSDKException] code:FailedOperation message:当前函数状态无法进行此操作...
```

中间还夹着 `NotOpenSSLWarning` / `urllib3` 警告。**写脚本解析错误时必须剥掉这两类噪音**，否则 `stderr[:400]` 这种截断会把真正的原因挤掉，只剩下没用的 usage 横幅 —— 排查时会被误导到错误方向（`deploy.py` 的 `_clean_stderr` / `_sdk_error` 就是为这个加的）。

---

## 三、常见报错

| 报错 / 现象 | 原因 | 处理 |
|:--|:--|:--|
| `AuthFailure.SecretIdNotFound` | 凭证缺失 | 让用户自行 `tccli configure` / `tccli auth login`。**不要索要密钥** |
| `AuthFailure.UnauthorizedOperation` | CAM 权限不足 | 检查子账号策略 |
| `InvalidParameterValue` | 参数取值错 | 对照 `references/api.md`；`NetConfig` 两个字段都必填 |
| `ResourceNotFound`（来自 `UpdateTrigger --Type http`） | **http 触发器不支持更新**（文档只支持 timer/ckafka） | 别重试、别改参数 —— 只能 `DeleteTrigger` + `CreateTrigger` 重建 |
| `FailedOperation: 当前函数状态无法进行此操作，请在函数状态正常时重试` | 代码更新/发布后函数处于 `Updating`，紧接着 `UpdateAlias` 被拒 | 轮询 `GetFunction` 的 `Status` 回到 `Active` 再操作 |
| `TriggerName already exists` | 同名 http 触发器已存在 | 函数 URL 的触发器名由 SCF 生成，先 `ListTriggers` 看真实名字 |
| 返回 200 但 body 是错误文本 | 函数没返回标准结构体 | 返回值加上 `statusCode` / `headers` / `body` |
| 上传后 `ImportError: No module named xxx` | 依赖没打进包，或 wheel 是错的 Python 版本 | 见 `api.md` 的「依赖打包」 |
| `Runtime` 不支持 `Python3.13` | SCF 最高只到 Python3.10 | 换运行时，或用 `CustomRuntime` 自带解释器 |
| 本地报 `invalid choice: 'XxxAction'` | 本地 tccli 版本落后 | `pip install -U tccli`；注意本地 schema 是快照，新接口可能完全缺失 |
| stdout 为空 + stderr 有 `usage:` 横幅 | tccli 首次调用该 action，接口定义未加载 | 重试一次即可。**不要据此判断参数错误** |
| `InvalidParameterValue.FunctionName`（用探针名测出来的） | 函数名不存在或不规范 | 正常现象，探针用不存在名字时会出现，可用于无副作用验证参数解析 |
| `Version not found`（bump-my-version） | `search` 模板和文件里的实际写法不一致 | 核对 `index.py` 里 `__version__ = "x.y.z"` 的引号与空格，必须和 `.bumpversion.toml` 的 `search` 完全一致 |
| `bump-my-version sample-config` 崩 `OSError: [Errno 22]` | 该子命令是交互式的，非 TTY 环境不可用 | 配置文件手写或复制模板，别用 `sample-config` |
| 网关返回 400 `domain[X] not found or empty` | 调用方透传了原始 Host，函数 URL 拒收 | **不是本 skill 的问题**，去 `tse-gateway-ops` 改路由的 `PreserveHost` |
| 网关 502 / 504 | 网关到后端不通，或超时叠加 | 见 `tse-gateway-ops` 的判定表 |

---

## 四、顺序陷阱

### 4.1 发布顺序（错了会报 FailedOperation）

```
bump → package → upload → 等 Active → publish → 等 Active → UpdateAlias
```

两处 `等 Active` 不能省：`UpdateFunctionCode` 和 `PublishVersion` 返回后函数还在 `Updating`，立刻做下一步会收到 `FailedOperation`。

### 4.2 删除资源必须倒序

```
网关路由 → 网关服务 → 函数 URL 触发器 → 别名 → 函数
```

前两步属 `tse-gateway-ops`。`DeleteFunction` 在触发器或别名还在时会失败。删 http 触发器时 `--Type http` 必传，`TriggerName` 要用 `ListTriggers` 取回的真实 id。

---

## 五、变更函数 URL 的连带影响（跨 skill）

`--stage qualifier` 会删除并重建触发器，**内网 URL 的 id 必然会变**。执行前先确认：

```sh
# 谁在用这个 URL？—— 用 tse-gateway-ops 的盘点能力查
python3 gateway.py --stage show --region "$REGION" \
  --gateway-id "$GATEWAY_ID" --grep <函数名>
```

确认后再动，动完立刻改上游：

```sh
python3 gateway.py --stage upstream --region "$REGION" \
  --gateway-id "$GATEWAY_ID" --service-id "<ServiceID>" --name <函数名> \
  --intranet-url 'https://<新 url-id>.in.<region>.tencentscf.com'
```

**用 `UpstreamType=Scf` 的网关服务不受影响** —— 它不经过函数 URL。这是路线 A 的一个额外好处。
