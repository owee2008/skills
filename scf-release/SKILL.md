---
name: scf-release
display_name: SCF 云函数交付与版本管理
description: 把 Python 函数交付到腾讯云 SCF —— 创建与 zip 更新、函数 URL 内外网开关、三段式发布（bump → upload → publish → alias）、版本与别名映射、灰度与秒级回滚。当用户提到「云函数部署」「函数 URL 只开内网」「上传和发布分开」「云函数版本管理」「SCF 回滚」「bump-my-version」时加载。网关侧的服务与路由见 tse-gateway-ops。
agent_created: true
version: 1.1.0
tags: [tencentcloud, scf, serverless, versioning, bump-my-version, intranet, function-url]
keywords: [云函数, SCF, 函数URL, 内网访问, 事件函数, CreateTrigger, NetConfig, PublishVersion, 别名, Alias, 灰度, 回滚, 版本管理, bump-my-version, zip部署, UpdateFunctionCode, 上传, 发布, semver]
---

# SCF 云函数交付与版本管理

把 Python 函数交付到腾讯云 SCF，管住它的入口与版本。

## 适用场景

- 「做个函数，只给内网调用」（开内网函数 URL）
- 「代码改了怎么更新上去」
- 「上传和发布要分开」「想能秒级回滚」「要灰度放量」
- 「semver 怎么和 SCF 版本号对上」

## 反面场景（不要用本 skill）

- **要把函数暴露成网关接口** → 网关侧的服务/路由/上游属于 `tse-gateway-ops`
- 后端是 CVM / 容器 → 本 skill 完全不适用
- 需要公网对外提供接口 → 直接开公网函数 URL 即可，不需要刻意关掉公网

## 职责边界

| | 本 skill（scf-release） | tse-gateway-ops |
|:--|:--|:--|
| 管什么 | 函数、函数 URL、版本、别名 | 网关服务、路由、上游、访问控制 |
| 脚本 | `scripts/deploy.py` | `scripts/gateway.py` |

唯一的交界处：**网关服务的上游可以指向函数**（选 `Scf` 类型或函数内网 URL）。这条契约的配置动作全在 `tse-gateway-ops`，本 skill 只负责把函数和 URL 准备好。

---

## 一、先钉死这 13 条事实（做错其中之一必返工）

1. **函数 URL 与触发器同级，事件函数和 Web 函数都支持。** 不存在「函数 URL 只有 Web 函数能用」这回事。区别只在事件函数收到 event 结构、Web 函数收到原始 HTTP 请求。
2. **函数 URL 没有独立 API —— 它和创建触发器共用 `CreateTrigger`**，`Type` 填 `http`。
3. **「只开内网」的正确写法**：`TriggerDesc.NetConfig = {"EnableIntranet": true, "EnableExtranet": false}`。
4. **SCF 控制台里的「网络配置」（VPC）管的是函数出站，不是访问控制。** 想让外部调不进来，改的是函数 URL 的 NetConfig，不是 VPC 配置。这两件事经常被混为一谈。
5. **内网函数 URL 的域名形态**：`https://<url-id>.in.<region>.tencentscf.com`（公网那条是 `https://<url-id>.<region>.tencentscf.com`）。公网 URL 一旦开过，即使内容一样也是另一个域名 —— 关掉公网不会让 URL 失效，但别把它写进配置。
6. **函数 URL 会校验 Host 必须是自己域名。** 所以任何反向代理/网关把请求转给它时，**不能透传原始 Host**，否则返回 `400 domain[X] not found or empty`。具体配置参数见 `tse-gateway-ops`。
7. **地域必须一致**：函数、函数 URL 及其调用方（如网关实例）必须在同一 region。
8. **内网接口在本地开发机（公网）测不了。** 必须从**同 VPC 内的 CVM**发起，或用控制台在线调试。别在内网测试环节浪费时间怀疑代码。
9. **上传 ≠ 发布 ≠ 上线，这是三个独立动作。** `UpdateFunctionCode` 只改 `$LATEST`（可覆盖、无版本号）；`PublishVersion` 把当前 `$LATEST` 冻结成**不可变整数版本**；而这两步都**不改变线上流量**。真正切流量的是「触发器指向哪一个版本/别名」。见第三节。
10. **SCF 的函数版本号是自增整数（1,2,3…），不可指定。** 所以「把 semver 同步成 SCF 版本号」在 API 层面做不到 —— 正确做法是**把 semver 写进 `PublishVersion` 的 `Description`**，用 `ListVersionByFunction` 读回做映射。别去设计「版本号 = 1.2.3」这种方案，会撞墙。
11. **http 触发器（函数 URL）的 `Qualifier` 改不了 —— 只能删除重建。** `UpdateTrigger` 官方文档写明「目前只支持 timer 触发器和 ckafka 触发器更新」，实测对 http 直接报 `ResourceNotFound`。代价是**重建后内网 URL 的 id 会变**（实测 `5o8f5pjbdq` → `k4zvlwjzsg`），旧 URL 立即失效，所有指向它的网关服务必须同步改上游。**因此绑定要在第一次就绑到别名，别绑死版本号。**
12. **`PublishVersion` / `UpdateAlias` 紧跟在代码上传后调用会失败。** 函数处于 `Updating` 状态时操作会收到 `FailedOperation「当前函数状态无法进行此操作，请在函数状态正常时重试」`。必须轮询 `GetFunction` 的 `Status` 回到 `Active` 再动别名。（`deploy.py` 已内置 `_wait_active`。）
13. **tccli 首次调用某个 action 可能失败，重试即成功。** 表现为 stdout 为空、stderr 出现 `usage:` 横幅。实测 `PublishVersion`、`GetAlias`、`CreateAlias` 首调都踩到过。**别把它当成参数写错去改代码。**（`deploy.py` 已内置一次自动重试。）
14. **🔴 版本快照的是「代码 + 配置」，不只是代码。** `PublishVersion` 会把**当时**的环境变量、VPC、超时、内存等**配置一并冻结进该版本**；之后在控制台或 `UpdateFunctionConfiguration` 改配置，**只改到 `$LATEST`，不会回灌到已发布的版本**。所以「别名指向的版本能跑，但它读不到你刚配的环境变量」是真实存在的状态。
    - **症状极具迷惑性**：函数配置页明明列着 6 个环境变量，运行时却全部为空。代码里 `_env('DB_HOST')` 拿到 `''`，PyMySQL 的 `host=''` 会退化成 `localhost`，于是报 `(2003, "Can't connect to MySQL server on 'localhost' ([Errno 111] Connection refused)")` ——**报的是 localhost，而不是你配的那个（不存在的）地址**，很容易误判成配置写错。
    - **判据（一条命令定性）**：对比两个视角的环境变量，不一致就是中招了。
      ```sh
      tccli scf GetFunction --region "$REGION" --FunctionName "$FN" --Namespace "$NS" \
        | jq '.Environment.Variables | length'                      # 当前配置（$LATEST）
      tccli scf GetFunction --region "$REGION" --FunctionName "$FN" --Namespace "$NS" \
        --Qualifier 1 | jq '.Environment.Variables | length'        # 别名指向的那个版本
      ```
    - **修法**：`PublishVersion` 出新版本 → `UpdateAlias` 把别名指过去。**凡是改了配置（环境变量 / VPC / 超时 / 内存 / 绑定），都必须「重新发布版本 + 切别名」才会对别名入口生效**，不是保存完就完事。
    - **日志也按版本分开**：`GetFunctionLogs` 不传 `--Qualifier` 取的是 `$LATEST` 的日志。经别名入口打进来的请求日志在**版本号**（如 `--Qualifier 1`）下面。**查到 `TotalCount = 0` 不代表函数没被调用**，先换 `--Qualifier` 再下结论 —— 实测因此误判过一次「函数没被触发」。

### 附注：tccli 的报错形态

tccli 在**任何失败**时都会先往 stderr 打一段 `usage:` 横幅，真正的异常在横幅**之后**（形如 `[TencentCloudSDKException] code:xxx message:yyy`），中间还夹着 urllib3/NotOpenSSL 警告。**写脚本解析错误时必须剥掉这两类噪音**，否则真正的原因会被挤掉（`deploy.py` 的 `_clean_stderr` / `_sdk_error` 就是干这个的）。

### Runtime 版本坑

SCF 支持的 Python 运行时为 `Python2.7 / 3.6 / 3.7 / 3.9 / 3.10`。**没有 3.13。** 本地用 3.13 开发时，依赖包要按 3.10 的 wheel 装（`pip install --python-version 3.10 --only-binary=:all: --target .`），否则上传后 `ImportError`。

### 依赖装在子目录时的经典翻车

SCF 只把 zip 的**根目录**放进 `sys.path`。把依赖装进 `vendor/` 之类的子目录后，整条链路上没有任何一步会报警：

- 本地测试**全绿** —— 测试脚本往往自己 `sys.path.insert(0, 'vendor')`，恰好把这个差异盖掉；
- `deploy.py --stage package/upload/function` 也**不报错** —— zip 里确实有依赖，`--src` 只是按扩展名过滤文件；
- 上传成功、函数 `Active`，一调用就 `ModuleNotFoundError: No module named 'pymysql'`，连 `import` 都过不去。

两条出路，选一条：

1. **把依赖铺到 zip 根目录**（SCF 的常规做法）：`pip install -r requirements.txt -t ./pkg`，`pkg/` 下直接是 `index.py` + `pymysql/`。
2. **保留子目录，由入口文件自己挂路径**：在 `import pymysql` **之前**加

   ```python
   for _base in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
       _vendor = os.path.join(_base, 'vendor')
       if os.path.isdir(_vendor) and _vendor not in sys.path:
           sys.path.insert(0, _vendor)
   ```

   `__file__` 和 `os.getcwd()` 两条都试 —— 运行时加载入口时 `__file__` 可能是相对路径（实测报错栈里就是 `File "./index.py"`）。

**上传前务必按 SCF 的方式验一次**：把 zip 解到临时目录，把该目录设为工作目录、且 `sys.path` 里**只留它**（去掉 site-packages，才能确认命中的是包内副本），再 `import` 入口模块并调用一次 handler。注意预检脚本里**不要手动插入 `vendor`**，否则又是自证清白。这套检查值得固化成脚本，上传前固定跑一遍。

---

## 二、执行流程

### Step 0 · 环境自检（必做）

```sh
command -v tccli >/dev/null 2>&1 && tccli cvm DescribeRegions >/dev/null 2>&1 && echo "TCCLI_OK" || echo "TCCLI_NEED_CHECK"
```

- `TCCLI_OK` → 继续
- 未安装 → `pip install -U tccli`。macOS 上 `pip install --user` 会落在 `~/Library/Python/3.x/bin/`，**该目录通常不在 PATH**，建议软链到 `~/.local/bin/`
- **报 `command not found: tccli` 但确实装过** → 非交互 shell 的 PATH 不含用户级 bin 目录（实测工具里跑的 Bash 就是这种情况，交互式终端反而正常）。**脚本与命令里一律用绝对路径调 tccli**，或设 `TCCLI_BIN=/path/to/tccli`。`scripts/deploy.py` 已内置兜底探测，按 `TCCLI_BIN` → PATH → `~/.local/bin` → `~/Library/Python/*/bin` → `/usr/local/bin` 顺序找
- 报 `AuthFailure.SecretIdNotFound` → 让**用户自己**执行 `tccli configure` 或 `tccli auth login`。**不代填、不索要、不打印密钥。**

确认变量：

```sh
REGION=ap-beijing            # 改成本地实际地域
FUNCTION_NAME=demo-fn
NAMESPACE=default
```

### Step 1 · 写函数

用 `templates/index.py` 作脚手架。事件函数**必须返回标准结构体**，否则经过函数 URL 会变成 200 + 错误文本：

```python
def main_handler(event, context):
    return {
        "isBase64Encoded": False,
        "statusCode": 200,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps({"ok": True}, ensure_ascii=False),
    }
```

事件函数收到的 `event`（函数 URL 调用时）只有这几个字段 —— 比 API 网关触发器少很多，**没有 `requestContext` / `pathParameters` / `headerParameters`**：

```json
{ "body": "...", "headers": {...}, "httpMethod": "POST", "path": "/", "queryString": {"a":"1"} }
```

### Step 2 · 部署函数

```sh
python3 scripts/deploy.py --stage function \
  --region "$REGION" --name "$FUNCTION_NAME" --src ./pkg
```

等价的裸 tccli 命令（`ZipFile` 必须是 zip 内容的 base64）：

```sh
tccli scf CreateFunction --region "$REGION" \
  --FunctionName "$FUNCTION_NAME" \
  --Type Event \
  --Runtime Python3.10 \
  --Handler index.main_handler \
  --MemorySize 128 --Timeout 30 \
  --Code "{\"ZipFile\":\"$B64\"}"

# 更新代码用这个，别重复 CreateFunction
tccli scf UpdateFunctionCode --region "$REGION" \
  --FunctionName "$FUNCTION_NAME" --Handler index.main_handler \
  --Code "{\"ZipFile\":\"$B64\"}"
```

代码包大小上限有**两个不同口径**，别记混（官方文档与客服均确认）：

| 参数 | 上限 |
|:--|--:|
| `UpdateFunctionCode` 顶层 `ZipFile` | **20 MB** |
| `Code.ZipFile`（推荐用这个） | **50 MB** |
| 解压后（代码 + Layer）总大小 | **500 MB** |

超过 20MB 就建议改走 COS（`deploy.py` 会在 >20MB 时告警、>50MB 时直接拒绝）：

```sh
tccli scf UpdateFunctionCode --region "$REGION" \
  --FunctionName "$FUNCTION_NAME" --Handler index.main_handler \
  --CodeSource Cos \
  --CosBucketName "<bucket>" --CosObjectName "/scf/${FUNCTION_NAME}-$(cat VERSION).zip" \
  --CosBucketRegion "$REGION"
```

### Step 3 · 开内网函数 URL（关键一步）

```sh
python3 scripts/deploy.py --stage url \
  --region "$REGION" --name "$FUNCTION_NAME" --namespace "$NAMESPACE"
```

裸命令：

```sh
tccli scf CreateTrigger --region "$REGION" \
  --FunctionName "$FUNCTION_NAME" \
  --TriggerName func_url \
  --Type http \
  --Namespace "$NAMESPACE" \
  --Enable OPEN \
  --TriggerDesc '{"AuthType":"NONE","NetConfig":{"EnableIntranet":true,"EnableExtranet":false}}'
```

创建后用 `tccli scf ListTriggers --FunctionName "$FUNCTION_NAME"` 取回内网 URL，记录到变量 `INTRANET_URL`。

- `AuthType`：`NONE` 免鉴权；`CAM` 走函数 URL 鉴权配置（需要调用方持有 CAM 权限，网关侧要额外处理签名，一般内网直连场景用 `NONE`）。
- **http 触发器的真实名称由 SCF 生成**（就是内网 URL 里那段 id，实测传 `func_url` 得到 `5o8f5pjbdq`），**传入的 `TriggerName` 不会生效**。后续要引用它（删除、重建、绑版本）都必须先 `ListTriggers` 取回真实名称。
- **同一函数不能重复创建 http 触发器**，也不要指望用 `UpdateTrigger` 改它 —— 事实 11：http 触发器只支持删除重建，重建会换 URL。
- **建的时候就把 `Qualifier` 定好**（`--Qualifier prod`），见第三节。不写默认是 `$LATEST`，等于「上传即上线」。

### Step 4 · 测试函数本身

```sh
tccli scf Invoke --region "$REGION" \
  --FunctionName "$FUNCTION_NAME" \
  --InvocationType RequestResponse \
  --ClientContext '{"path":"/ping","httpMethod":"GET"}'
```

只验证代码逻辑。**这一层过了不代表内网链路通了** —— 链路要到 VPC 内 CVM 上才能验（事实 8）。

| 现象 | 结论 | 下一步 |
|:--|:--|:--|
| 本地 curl 内网 URL 超时 | **正常**，不是故障 | 换 VPC 内 CVM 重测 |
| 返回 200 但 body 是错误文本 | 函数没返回标准结构体 | 回 Step 1 改返回格式 |
| 网关返回 400 `domain[X] not found or empty` | 调用方透传了原始 Host，函数 URL 拒收 | 去 `tse-gateway-ops` 改路由的 `PreserveHost` |
| 网关 502 / 504 | 网关到后端不通 | 见 `tse-gateway-ops` 的连通性排查 |

### Step 5 · 要暴露成网关接口时

函数和 URL 就绪后，接着用 **`tse-gateway-ops`** 建网关服务与路由。本 skill 到此结束 —— 不要在 `deploy.py` 里找网关参数，那里刻意没有。

### Step 6 · 回收

```sh
# 注意：TriggerName 必须填 ListTriggers 取回的真实 id，Type 必须带，否则删不掉
tccli scf DeleteTrigger --region "$REGION" --FunctionName "$FUNCTION_NAME" \
  --TriggerName "<url-id>" --Type http --Namespace "$NAMESPACE"

# 别名要先摘掉才能干净地删函数
tccli scf DeleteAlias --region "$REGION" --FunctionName "$FUNCTION_NAME" --Name prod

tccli scf DeleteFunction --region "$REGION" --FunctionName "$FUNCTION_NAME"
```

**顺序不能反**：若已接网关，先删网关路由 → 删网关服务（在 `tse-gateway-ops`）→ 再删函数 URL 触发器 → 别名 → 函数。`DeleteFunction` 在触发器或别名还在时会失败。

---

## 三、迭代发布：上传 / 发布 / 切流量 是三个独立动作

**结论：能拆，而且必须拆。** 但只有前两段是 API 现成支持的，第三段取决于你的入口类型。

| 段 | 动作 | 接口 | 是否改变线上流量 |
|:--|:--|:--|:--|
| ① 上传 | 把代码写进 `$LATEST` | `UpdateFunctionCode` | **否**（仅当触发器不绑 `$LATEST`） |
| ② 发布 | 把当前 `$LATEST` 冻结成不可变整数版本 | `PublishVersion` | **否** |
| ③ 切流量 | 让入口指向新版本或别名 | `UpdateAlias` | **是** |

> ⚠ **改配置（环境变量 / VPC / 超时 / 内存）走的也是这三段，不是「保存即生效」。** 配置改完只落在 `$LATEST`，别名指向的旧版本仍用旧配置 —— 只做 ① 不做 ②③ 等于白改。见事实 14。

### 3.1 版本号管理（bump-my-version）

`templates/.bumpversion.toml` + `templates/VERSION` 直接复制到函数源码目录使用。`current_version` 是权威版本号，bump 时同步写进 `VERSION` 和 `index.py` 的 `__version__`。

```sh
bump-my-version bump patch     # 0.1.0 -> 0.1.1
bump-my-version bump minor     # 0.1.0 -> 0.2.0
bump-my-version show-bump      # 只预演，不改文件
```

三个坑：

- **`bump-my-version sample-config` 在非 TTY 环境会崩**（`OSError: [Errno 22] Invalid argument`，prompt_toolkit 报的）。配置文件手写或从本 skill 复制。
- **`index.py` 里 `__version__ = "x.y.z"` 那一行的写法是匹配锚点**，改了格式（比如换成单引号或加空格不一致）bump 就找不到，会静默跳过。`ignore_missing_version` 默认 false 时会报 `Version not found`，可以据此判断。
- **`__version__` 必须进响应体/响应头**，否则你没有任何手段证明线上跑的是哪个版本。`templates/index.py` 已内置 `X-Scf-Version` 响应头。

**semver 与 SCF 版本号的关系（重要）**：SCF 版本号是自增整数，不可指定。semver 只能写进 `PublishVersion` 的 `Description`：

```sh
tccli scf PublishVersion --region "$REGION" \
  --FunctionName "$FUNCTION_NAME" --Namespace "$NAMESPACE" \
  --Description "semver=0.4.0 sha=a1b2c3d"
```

读回映射：`tccli scf ListVersionByFunction --FunctionName "$FUNCTION_NAME" --Limit 50`。

### 3.2 三段式命令序列

```sh
# ① 提版本（只改本地文件）
python3 scripts/deploy.py --stage bump --name "$FUNCTION_NAME" --src ./pkg --bump-part minor

# ② 打包留档（不碰云，产物可送审）
python3 scripts/deploy.py --stage package --name "$FUNCTION_NAME" --src ./pkg
#    → ./pkg/dist/${FUNCTION_NAME}-0.4.0.zip

# ③ 只上传到 $LATEST（线上不变）
python3 scripts/deploy.py --stage upload --name "$FUNCTION_NAME" --src ./pkg
#    也可以用现成产物：--zip ./pkg/dist/xxx-0.4.0.zip

# ④ 发布版本 + 把别名指向它（仍然不影响线上）
python3 scripts/deploy.py --stage publish --name "$FUNCTION_NAME" --src ./pkg --alias prod

# ⑤ 一条命令走完 ①→④
python3 scripts/deploy.py --stage release --name "$FUNCTION_NAME" --src ./pkg \
  --bump-part minor --alias prod

# ⑥ 查版本与别名映射
python3 scripts/deploy.py --stage versions --name "$FUNCTION_NAME" --src ./pkg
```

### 3.3 让切流量真的可行：触发器要绑别名

**最容易踩的坑在这里。** 触发器默认 `Qualifier: $LATEST`，此时「上传即上线」—— 第 ③ 步做完线上就变了，灰度、留档、回滚全部无从谈起。

| 触发器 Qualifier | 上传后的效果 |
|:--|:--|
| `$LATEST`（默认） | **立即上线**，无版本、无法回滚 |
| 别名（如 `prod`） | 线上不动，切流量靠改别名 |

**但 http 触发器的 Qualifier 改不了**（事实 11），只能删除重建 —— 一次性成本：

```sh
# 1) 记下旧 URL
tccli scf ListTriggers --region "$REGION" --FunctionName "$FUNCTION_NAME"
# 2) 删除（TriggerName 用真实 id）
tccli scf DeleteTrigger --region "$REGION" --FunctionName "$FUNCTION_NAME" \
  --TriggerName "<旧 url-id>" --Type http --Namespace "$NAMESPACE"
# 3) 重建，直接绑别名。NetConfig 要原样保留
tccli scf CreateTrigger --region "$REGION" --FunctionName "$FUNCTION_NAME" \
  --TriggerName "${FUNCTION_NAME}-url" --Type http --Namespace "$NAMESPACE" \
  --Enable OPEN --Qualifier prod \
  --TriggerDesc '{"AuthType":"NONE","NetConfig":{"EnableIntranet":true,"EnableExtranet":false}}'
```

`deploy.py --stage qualifier --qualifier prod` 把 1~3 步包好了，并在最后打印出新 URL 与「哪些网关服务会受影响、该用什么命令改」。

**⚠ 第 4 步是破坏性跨边界动作**：新 URL 的 id 变了，旧地址立即失效，任何上游指向它的**网关服务**都会 503。改上游属于 `tse-gateway-ops` 的职责：

```sh
python3 gateway.py --stage upstream --region "$REGION" \
  --gateway-id "$GATEWAY_ID" --service-id "<ServiceID>" --name "$FUNCTION_NAME" \
  --intranet-url 'https://<新 url-id>.in.<region>.tencentscf.com'
```

**做完这一次之后，以后每次切换只是个改别名：**

```sh
python3 scripts/deploy.py --stage alias --name "$FUNCTION_NAME" \
  --alias prod --to-version 5
```

**回滚同理 —— 把别名指回上一个版本号，秒级生效，不重建任何东西。**

### 3.4 灰度放量

别名支持给附加版本分配权重（主版本 + 一个附加版本，最多一个）：

```json
{
  "FunctionName": "demo-fn",
  "Name": "prod",
  "FunctionVersion": "3",
  "RoutingConfig": { "AdditionalVersionWeights": [{"Version": "4", "Weight": 0.1}] }
}
```

含义是 v3 占 90%、v4 占 10%。逐步调权重到 1.0 后，再把 `FunctionVersion` 直接改成 `4`。

**注意**：函数 URL 直接绑**数字版本**时不会参与别名的权重分配，必须绑**别名**才有灰度能力。

### 3.5 另一条更干净的路（入口在网关时不重建触发器）

若网关服务用 `UpstreamType: Scf` 且 `ScfLambdaQualifier` 指向别名，切流量可以只改网关服务那一个字段，**完全绕开函数 URL**，不需要重建触发器、不用担心 URL 变化。配置方式见 `tse-gateway-ops`。已有函数已在跑函数 URL 时这只是可选项，不是必须迁移。

### 3.6 实测证据（三段式的完整验证）

在 `demo-intranet-fn` 上跑出的真实数据，可作为流程正确性的判据：

| 步骤 | 触发器 Qualifier | `$LATEST` 代码 | 线上实测版本 |
|:--|:--|:--|:--|
| 起始 | `$LATEST` | 0.3.0 | 0.3.0 |
| bump→0.4.0 + **只上传** | `$LATEST` | 0.4.0 | **0.4.0**（上传即上线，证明了问题） |
| 触发器重建绑 `prod`(→v3) | `prod` | 0.4.0 | **0.3.0**（隔离生效） |
| `PublishVersion` → v4 | `prod` | 0.4.0 | 0.3.0（发布不影响线上） |
| `UpdateAlias prod→4` | `prod` | 0.4.0 | **0.4.0**（切流量） |
| `UpdateAlias prod→3` | `prod` | 0.4.0 | **0.3.0**（回滚） |

---

## 四、安全红线

- **不向用户索要 SecretId / SecretKey**，不执行任何会打印凭证的命令（尤其 `tccli configure list`）。
- 创建/删除类操作用户确认后再执行。**删除 http 触发器会让内网 URL 失效**，属于对外可见的破坏性动作，必须先确认再动。
- 内网函数 URL 默认 `AuthType: NONE`，等于内网内可任意调用 —— 提醒用户按需加鉴权（或由网关侧做访问控制，见 `tse-gateway-ops`）。

## 五、参数速查

接口字段见 `references/api.md`，报错处理见 `references/troubleshooting.md`。
