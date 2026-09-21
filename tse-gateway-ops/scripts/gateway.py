#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TSE 云原生网关运维 —— 服务、路由、上游。

覆盖：网关服务与路由的创建、上游切换、现状盘点与冲突预检。
这是纯粹的**网关侧**工具，不依赖任何特定后端：上游可以是 SCF 云函数、
CVM、容器或 IP 列表。

针对云函数的场景有两处接口契约（本脚本都支持）：
  - `--upstream scf`  ：网关直接调 SCF 内网接口，不经过函数 URL
  - `--upstream url`  ：网关把请求转发到函数的内网 URL（HostIP）
函数本身的创建、函数 URL 的开通、版本发布都在 skill `scf-release`，
本脚本不碰那些。

依赖：tccli 已安装并完成凭证配置。本脚本不接触、不打印任何密钥。

用法：
  # 0) 动手前先盘现状（必做，共享网关上尤其重要）
  python3 gateway.py --stage show --region ap-beijing --gateway-id gateway-xxxxxxxx

  # 1) 建服务 —— 后端选 Scf（推荐，不依赖函数 URL）
  python3 gateway.py --stage service --region ap-beijing \
      --gateway-id gateway-xxxxxxxx --name demo-fn \
      --upstream scf --function-name demo-fn --function-type Event \
      --namespace default

  # 1b) 建服务 —— 后端指向内网函数 URL
  python3 gateway.py --stage service --region ap-beijing \
      --gateway-id gateway-xxxxxxxx --name demo-fn \
      --upstream url \
      --intranet-url 'https://1318516741-xxxx.in.ap-beijing.tencentscf.com' \
      --intranet-port 80 --service-protocol http

  # 2) 建路由（--strip-path 见 SKILL.md 的硬要求）
  python3 gateway.py --stage route --region ap-beijing \
      --gateway-id gateway-xxxxxxxx --name demo-fn \
      --service-id <上一步返回的 ServiceID> \
      --route-path /demo --strip-path

  # 3) 切换已有服务的上游（函数 URL 重建后必须做这一步）
  python3 gateway.py --stage upstream --region ap-beijing \
      --gateway-id gateway-xxxxxxxx --service-id <ServiceID> --name demo-fn \
      --intranet-url 'https://<新 url-id>.in.ap-beijing.tencentscf.com'

  # 4) 查单条路由详情（拿 RouteID，改路由配置前必做）
  python3 gateway.py --stage route-info --region ap-beijing \
      --gateway-id gateway-xxxxxxxx --name demo-fn
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

DEFAULT_LIMIT = 200          # 默认分页只返回 10 条，实测会误判环境差 17~20 倍
ROUTE_PROTOCOLS = ["http", "https"]


# ---------------------------------------------------------------- tccli 调用

def _extract_json(text):
    """从夹杂版本提示/警告的输出里抠出 JSON 主体。"""
    if not text:
        return None
    m = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _find_tccli():
    """定位 tccli 可执行文件。

    非交互 shell 的 PATH 常常不含 ~/.local/bin（macOS 上 pip --user 的常见落点），
    所以不能只靠 PATH，必须兜底探测已知目录。
    """
    env_bin = os.environ.get("TCCLI_BIN")
    if env_bin and os.access(env_bin, os.X_OK):
        return env_bin

    found = shutil.which("tccli")
    if found:
        return found

    home = os.path.expanduser("~")
    candidates = [os.path.join(home, ".local", "bin", "tccli")]

    py_root = os.path.join(home, "Library", "Python")
    if os.path.isdir(py_root):
        for ver in sorted(os.listdir(py_root), reverse=True):
            candidates.append(os.path.join(py_root, ver, "bin", "tccli"))

    candidates += ["/usr/local/bin/tccli", "/opt/homebrew/bin/tccli"]

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


TCCLI = _find_tccli()


def _clean_stderr(text):
    """剔掉 tccli 每次都刷的噪音，只留可能有用的行。

    tccli 在**任何失败**时都会往 stderr 打一段 usage 横幅，真正的异常在横幅之后。
    另外 urllib3/NotOpenSSL 警告也混在同一条流里。不清理的话，真正的原因会被挤掉。
    """
    kept = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "NotOpenSSLWarning" in stripped or stripped.startswith("warnings.warn"):
            continue
        if "urllib3" in stripped:
            continue
        if (stripped.startswith("usage:")
                or stripped.startswith("To tccli help")
                or stripped.startswith("tccli help")
                or stripped.startswith("tccli configure")
                or stripped.startswith("tccli service")):
            continue
        kept.append(stripped)
    return kept


def _sdk_error(lines):
    """从清理后的 stderr 里挑出真正的异常行。"""
    for line in lines:
        if "TencentCloudSDKException" in line:
            return line
    for line in lines:
        if "code:" in line and "message:" in line:
            return line
    return None


def tccli(region, service, action, **params):
    """调用 tccli，返回 Response 字典；失败时抛 RuntimeError。

    stdout / stderr 分流：stderr 单独收集，避免把 warning 当结果吞掉。
    非交互 shell 里 tccli 首次调用某个 action 时可能因加载接口定义而返回空 stdout，
    这种情况自动重试一次。
    """
    if not TCCLI:
        raise RuntimeError(
            "找不到 tccli。先执行 pip install -U tccli，"
            "或用 TCCLI_BIN=/path/to/tccli 指定路径。"
        )
    cmd = [TCCLI, service, action]
    if region:
        cmd += ["--region", region]
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        cmd += ["--{}".format(key), str(value)]

    data = None
    for attempt in (1, 2):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            raise RuntimeError("找不到 tccli，请先执行 pip install -U tccli")

        data = _extract_json(proc.stdout)
        if data is not None:
            break
        if attempt == 1:
            print("  [retry] tccli 未返回 JSON，重试一次（{}/{}）".format(action, service))
            time.sleep(1)
            continue

    if data is None:
        lines = _clean_stderr(proc.stderr)
        reason = _sdk_error(lines) or "\n  ".join(lines[-6:]) or "(stderr 为空)"
        raise RuntimeError(
            "{}.{} 调用失败：\n  {}\n  cmd: {}".format(service, action, reason, " ".join(cmd))
        )

    resp = data.get("Response", data)
    error = resp.get("Error")
    if error:
        raise RuntimeError("{}: {}".format(error.get("Code"), error.get("Message")))
    return resp


def tccli_optional(region, service, action, **params):
    """调用但允许失败（用于「先查是否存在」这类探测）。"""
    try:
        return tccli(region, service, action, **params)
    except RuntimeError as exc:
        return {"_error": str(exc)}


def _pick(mapping, keys):
    for key in keys:
        if mapping.get(key):
            return mapping[key]
    return None


def _need(value, flag):
    if not value:
        raise RuntimeError("{} 必填".format(flag))
    return value


# ---------------------------------------------------------------- 盘点

def fetch_services(args):
    """拉全量服务列表。**必须带 Limit** —— 默认只给 10 条，会误判环境。"""
    resp = tccli(args.region, "tse", "DescribeCloudNativeAPIGatewayServices",
                 GatewayId=args.gateway_id, Limit=args.limit)
    result = resp.get("Result") or resp
    return result.get("ServiceList") or [], result.get("TotalCount")


def fetch_routes(args):
    """拉全量路由列表。**必须带 Limit**。"""
    resp = tccli(args.region, "tse", "DescribeCloudNativeAPIGatewayRoutes",
                 GatewayId=args.gateway_id, Limit=args.limit)
    result = resp.get("Result") or resp
    return result.get("RouteList") or [], result.get("TotalCount")


def stage_show(args):
    """盘现状：服务、路由、公网状态，并做重名与路径冲突预检。"""
    print("[show] 网关 {} @{}".format(args.gateway_id, args.region or "(默认地域)"))

    inst = tccli_optional(args.region, "tse", "DescribeCloudNativeAPIGateway",
                          GatewayId=args.gateway_id).get("Result") or {}
    if inst:
        print("  实例：{}  版本={}  引擎={}".format(
            inst.get("Name"), inst.get("GatewayVersion") or inst.get("Type"),
            inst.get("EngineRegion") or "-"))
        internet = inst.get("EnableInternet")
        print("  公网：{}   内网 VPC：{}".format(
            "⚠ 已开启（实例级，新增路由同样公网可达）" if internet else "未开启",
            inst.get("VpcId") or "-"))
    else:
        print("  ⚠ 未能读到实例信息（权限或 ID 有误），继续用列表接口盘点")

    services, s_total = fetch_services(args)
    routes, r_total = fetch_routes(args)

    print()
    print("  服务 {} 个（返回 {} 条，Limit={}）".format(
        s_total if s_total is not None else "?", len(services), args.limit))
    if s_total and len(services) < s_total:
        print("  ⚠ 返回条数少于总数，加大 --limit 再拉一次")

    shown = [s for s in services
             if not args.grep or args.grep in (s.get("Name") or "")]
    for s in shown[:args.max_rows]:
        print("    {:<34} {:<8} {}".format(
            s.get("Name"), s.get("UpstreamType") or "-", s.get("ID") or ""))
    if len(shown) > args.max_rows:
        print("    … 其余 {} 条省略（用 --max-rows 调整，或 --grep 过滤）".format(
            len(shown) - args.max_rows))

    print()
    print("  路由 {} 条（返回 {} 条）".format(
        r_total if r_total is not None else "?", len(routes)))
    shown_r = [r for r in routes
               if not args.grep
               or args.grep in (r.get("Name") or "")
               or any(args.grep in p for p in (r.get("Paths") or []))]
    for r in shown_r[:args.max_rows]:
        print("    {:<40} {:<24} {}".format(
            ",".join(r.get("Paths") or []), r.get("Name") or "", r.get("ID") or ""))
    if len(shown_r) > args.max_rows:
        print("    … 其余 {} 条省略".format(len(shown_r) - args.max_rows))

    # ---- 冲突预检：共享网关上动手前必须先看这个 ----
    if args.name or args.route_path:
        print()
        print("  [precheck] 新增前冲突检查")
        if args.name:
            svc_name = args.service_name or "{}-svc".format(args.name)
            rt_name = args.route_name or "{}-route".format(args.name)
            hit_s = [s.get("Name") for s in services if s.get("Name") == svc_name]
            hit_r = [r.get("Name") for r in routes if r.get("Name") == rt_name]
            print("    服务名 {}：{}".format(
                svc_name, "⚠ 已存在" if hit_s else "✓ 可用"))
            print("    路由名 {}：{}（RouteName 实例级唯一）".format(
                rt_name, "⚠ 已存在" if hit_r else "✓ 可用"))
        if args.route_path:
            owners = []
            for r in routes:
                for p in (r.get("Paths") or []):
                    if p == args.route_path or p.startswith(args.route_path.rstrip("/") + "/"):
                        owners.append("{} ({})".format(p, r.get("Name")))
            print("    路径 {}：{}".format(
                args.route_path,
                "⚠ 已被占用 -> " + "; ".join(owners) if owners else "✓ 未被占用"))

    print()
    print("  提醒：实例级配置（公网开关 / IP 访问控制 / CORS / 限流）一改波及全部业务，")
    print("        在共享网关上不要动。只做「新增服务 + 新增路由」这类纯增量。")


def stage_route_info(args):
    """查路由详情，取 RouteID（改路由配置前必做）。"""
    routes, _ = fetch_routes(args)
    hit = [r for r in routes
           if (args.name and args.name in (r.get("Name") or ""))
           or (args.route_path and args.route_path in (r.get("Paths") or []))]
    if not hit:
        raise RuntimeError("没找到匹配的路由（--name {} / --route-path {}）".format(
            args.name, args.route_path))
    for r in hit:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    print()
    print("  改配置用：tccli tse ModifyCloudNativeAPIGatewayRoute \\")
    print("    --GatewayId {} --ServiceID <ServiceID> --RouteID <ID> \\".format(args.gateway_id))
    print("    --RouteName <名称> --Methods '[\"GET\",\"POST\"]' --Paths '[\"/x\"]' \\")
    print("    --Protocols '[\"http\",\"https\"]' --PreserveHost false --StripPath true")
    print("  ⚠ Modify 的 GatewayId / ServiceID / RouteID 三个都必填，是整体覆盖不是局部改。")
    print("  ⚠ PreserveHost 必须 false、StripPath 必须 true —— 见 SKILL.md 硬要求。")


# ---------------------------------------------------------------- 服务与路由

def build_upstream(args):
    """按 --upstream 组装 UpstreamInfo 与 UpstreamType。"""
    if args.upstream == "scf":
        fn = args.function_name or args.name
        if not fn:
            raise RuntimeError("--upstream scf 需要 --function-name（或 --name）")
        info = {
            "ScfType": args.function_type,
            "ScfNamespace": args.namespace,
            "ScfLambdaName": fn,
            "ScfLambdaQualifier": args.qualifier or "$LATEST",
        }
        print("  上游：Scf  函数={} 类型={} ns={} qualifier={}".format(
            fn, args.function_type, args.namespace, info["ScfLambdaQualifier"]))
        print("  （直接走 SCF 内网接口，不经过函数 URL —— 不受 URL 开关与域名解析影响）")
        return "Scf", info

    if not args.intranet_url:
        raise RuntimeError("--upstream url 必须提供 --intranet-url")
    host = args.intranet_url.replace("https://", "").replace("http://", "").rstrip("/")
    info = {"Host": host, "Port": args.intranet_port}
    print("  上游：HostIP  {}:{}".format(host, args.intranet_port))
    print("  （依赖函数 URL 的内网端点，且网关要能解析 *.in.<region>.tencentscf.com）")
    return "HostIP", info


def stage_service(args):
    """在网关上创建服务。"""
    _need(args.gateway_id, "--gateway-id")
    name = args.service_name or "{}-svc".format(args.name or "gw")
    print("[service] 创建服务 {}（协议 {}，超时 {}ms，Retries 0）".format(
        name, args.service_protocol, args.service_timeout))
    print("  ⚠ Retries 固定 0：官方示例给的是 3，抄到非幂等函数上会造成重复执行。")

    up_type, up_info = build_upstream(args)

    resp = tccli(
        args.region, "tse", "CreateCloudNativeAPIGatewayService",
        GatewayId=args.gateway_id,
        Name=name,
        Protocol=args.service_protocol,
        Timeout=args.service_timeout,
        Retries=0,
        UpstreamType=up_type,
        UpstreamInfo=up_info,
    )
    print("  原始返回: {}".format(json.dumps(resp, ensure_ascii=False)))

    service_id = args.service_id or _pick(resp.get("Result") or {},
                                          ("ServiceID", "ServiceId", "ID", "Id"))
    if not service_id:
        raise RuntimeError("未能从返回中解析 ServiceID，请用 --service-id 显式指定后重跑 --stage route")
    print("  ✓ 服务已创建 ServiceID={}".format(service_id))
    print()
    print("  下一步建路由：")
    print("    python3 gateway.py --stage route --region {} \\".format(args.region or "<region>"))
    print("      --gateway-id {} --name {} \\".format(args.gateway_id, args.name or "<name>"))
    print("      --service-id {} --route-path {} --strip-path".format(
        service_id, args.route_path))
    return service_id


def stage_route(args):
    """在服务下创建路由。"""
    _need(args.gateway_id, "--gateway-id")
    _need(args.service_id, "--service-id")
    name = args.route_name or "{}-route".format(args.name or "gw")

    print("[route] 创建路由 {} -> {}".format(name, args.route_path))
    print("  PreserveHost=false   StripPath={}".format(args.strip_path))

    if not args.strip_path:
        print("  ⚠ StripPath 关着：请求 /demo/ping 会原样转发给后端。")
        print("    仅当后端自己就认识带前缀的路径时才这样配，否则会 404。")

    tccli(
        args.region, "tse", "CreateCloudNativeAPIGatewayRoute",
        GatewayId=args.gateway_id,
        ServiceID=args.service_id,
        RouteName=name,
        Methods=args.route_methods,
        Paths=[args.route_path],
        Protocols=ROUTE_PROTOCOLS,
        PreserveHost=False,
        StripPath=args.strip_path,
    )
    print("  ✓ 路由已创建")
    print()
    print("  验证：")
    print("    内网（VPC 内 CVM）：curl -sv http://<网关内网IP>{0} -d '{{}}'".format(args.route_path))
    print("    公网（实例已开公网时）：curl -sv http://<网关公网IP>{0} -d '{{}}'".format(args.route_path))


def stage_upstream(args):
    """切换已有服务的上游地址。

    典型触发场景：函数 URL 的触发器被重建，内网 URL 的 id 变了，旧地址立即失效。
    ModifyCloudNativeAPIGatewayService 是**整体覆盖**，所有字段都要带上。
    """
    _need(args.gateway_id, "--gateway-id")
    if not args.service_id:
        raise RuntimeError(
            "--service-id 必填。先用 --stage show --grep <名字> 找到 ServiceID。")

    name = args.service_name or "{}-svc".format(args.name or "gw")
    up_type, up_info = build_upstream(args)

    print("[upstream] 切换服务 {} 的上游".format(name))
    tccli(args.region, "tse", "ModifyCloudNativeAPIGatewayService",
          GatewayId=args.gateway_id, ID=args.service_id,
          Name=name,
          Protocol=args.service_protocol, Timeout=args.service_timeout, Retries=0,
          UpstreamType=up_type,
          UpstreamInfo=up_info)

    print("  ✓ 上游已切换为 {}: {}".format(up_type, json.dumps(up_info, ensure_ascii=False)))
    print("  ⚠ 改完头几秒可能返回 503 {\"message\":\"name resolution failed\"} ——")
    print("    Kong 的 DNS 缓存还没过期，等几秒重试即恢复，别当成配置错去乱改。")


# ---------------------------------------------------------------- 入口

def main():
    p = argparse.ArgumentParser(description="TSE 云原生网关运维（服务 / 路由 / 上游）")
    p.add_argument("--stage", required=True,
                   choices=["show", "service", "route", "upstream", "route-info"],
                   help="show=盘点与冲突预检；service/route=建服务与路由；"
                        "upstream=切上游；route-info=查路由详情取 RouteID")
    p.add_argument("--region", default=None,
                   help="地域。省略则用 tccli configure 里的默认地域")
    p.add_argument("--gateway-id", help="网关实例 ID，如 gateway-xxxxxxxx")
    p.add_argument("--name", help="这套配置的名字；服务名默认 <name>-svc，路由名默认 <name>-route")
    p.add_argument("--service-name", help="显式指定服务名（默认 <name>-svc）")
    p.add_argument("--route-name", help="显式指定路由名（默认 <name>-route）")

    # ---- 上游 ----
    p.add_argument("--upstream", default="scf", choices=["scf", "url"],
                   help="scf=网关直连云函数；url=转发到函数的内网 URL")
    p.add_argument("--function-name", help="--upstream scf 时的函数名（默认同 --name）")
    p.add_argument("--function-type", default="Event",
                   help="--upstream scf 时必填且必须与函数实际类型一致：Event / HTTP")
    p.add_argument("--namespace", default="default")
    p.add_argument("--qualifier", default=None,
                   help="--upstream scf 时绑定函数版本或别名，默认 $LATEST")
    p.add_argument("--intranet-url", help="--upstream url 时必填，如 https://xxx.in.ap-beijing.tencentscf.com")
    p.add_argument("--intranet-port", type=int, default=80)

    # ---- 服务 ----
    p.add_argument("--service-id", help="已知 ServiceID 时直接指定")
    p.add_argument("--service-protocol", default="http", choices=["http", "https"])
    p.add_argument("--service-timeout", type=int, default=15000,
                   help="单位毫秒。链路超时取最小值：网关服务 → 函数 URL → 函数自身")

    # ---- 路由 ----
    p.add_argument("--route-path", default="/demo")
    p.add_argument("--route-methods", nargs="+", default=["GET", "POST"])
    p.add_argument("--strip-path", action="store_true",
                   help="转发前剥离路由前缀。后端按 /ping 匹配时必须开，"
                        "否则会收到 /demo/ping 而返回 404")

    # ---- 盘点 ----
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                   help="Describe 的 Limit。默认 200 —— 接口默认只返回 10 条，"
                        "在共享网关上会严重误判")
    p.add_argument("--grep", help="--stage show 时按名称/路径过滤")
    p.add_argument("--max-rows", type=int, default=40, help="--stage show 每类最多打印几行")

    args = p.parse_args()

    try:
        if args.stage == "show":
            _need(args.gateway_id, "--gateway-id")
            stage_show(args)
        elif args.stage == "service":
            stage_service(args)
        elif args.stage == "route":
            stage_route(args)
        elif args.stage == "upstream":
            stage_upstream(args)
        elif args.stage == "route-info":
            _need(args.gateway_id, "--gateway-id")
            stage_route_info(args)
    except RuntimeError as exc:
        print("\n✗ 失败：{}".format(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
