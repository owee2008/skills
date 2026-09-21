#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SCF 云函数交付与版本管理。

覆盖：函数创建 / zip 更新 / 内网函数 URL / 三段式发布（bump→upload→publish→alias）
      / 版本与别名映射 / 灰度与回滚。

依赖：tccli 已安装并完成凭证配置（tccli configure / tccli auth login）。
本脚本不接触、不打印任何密钥。

**网关部分不在本脚本范围内。** 需要把函数 URL 暴露成 TSE 云原生网关接口时，
用另一个 skill `tse-gateway-ops`（服务与路由的创建、上游切换）。
两边唯一的接口契约是：网关服务上游可指向函数的内网 URL，或直接选 Scf 类型。

用法：
  首次部署：
  # 1) 建/更新函数
  python3 deploy.py --stage function --region ap-guangzhou \
      --name demo-fn --src ./pkg

  # 2) 开内网函数 URL（只开内网，不开公网）
  python3 deploy.py --stage url --region ap-guangzhou --name demo-fn

  迭代发布（上传与发布分开，三段式）：
  # 3) 提版本号（只改本地文件）
  python3 deploy.py --stage bump --name demo-fn --src ./pkg --bump-part patch

  # 4) 打包出 zip 产物（不碰云，可留档/送审）
  python3 deploy.py --stage package --name demo-fn --src ./pkg

  # 5) 只上传（更新 $LATEST，线上流量不受影响）
  python3 deploy.py --stage upload --name demo-fn --src ./pkg
  python3 deploy.py --stage upload --name demo-fn --zip dist/demo-fn-0.2.0.zip

  # 6) 发布版本（冻结成不可变版本号）+ 绑定别名
  python3 deploy.py --stage publish --name demo-fn --src ./pkg --alias prod

  # 7) 一条命令走完 3→6
  python3 deploy.py --stage release --name demo-fn --src ./pkg \
      --bump-part patch --alias prod

  # 8) 查版本与别名映射
  python3 deploy.py --stage versions --name demo-fn --src ./pkg

  # 9) 查询内网函数 URL
  python3 deploy.py --stage show-url --region ap-guangzhou --name demo-fn

  # 10) 把函数 URL 触发器绑到别名（这一步才真正切换线上流量）
  python3 deploy.py --stage qualifier --region ap-guangzhou \
      --name demo-fn --qualifier prod

  # 11) 只移动别名指向（最小回滚动作，不重建任何东西）
  python3 deploy.py --stage alias --name demo-fn --alias prod --to-version 3
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "node_modules",
             ".pytest_cache", "dist", ".dist", "venv", ".venv"}
SKIP_EXTS = (".pyc", ".pyo", ".zip", ".log", ".md")
SKIP_FILES = {".DS_Store", ".bumpversion.toml", ".bumpversion.cfg", "bumpversion.cfg"}


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
    这种情况自动重试一次（实测 PublishVersion 首调踩过）。
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
        # stdout 没 JSON：可能是接口定义未加载，重试一次
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


# ---------------------------------------------------------------- 打包

def build_zip_base64(src_dir):
    if not os.path.isdir(src_dir):
        raise RuntimeError("源码目录不存在：{}".format(src_dir))

    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if name in SKIP_FILES or name.endswith(SKIP_EXTS):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, src_dir)
                zf.write(full, rel)
                count += 1

    if count == 0:
        raise RuntimeError("源码目录为空：{}".format(src_dir))

    raw = buf.getvalue()
    print("  打包 {} 个文件，zip {} 字节".format(count, len(raw)))
    if len(raw) > 50 * 1024 * 1024:
        raise RuntimeError("zip 超过 50MB，请改用 CosBucketName + CosObjectName 上传")
    return base64.b64encode(raw).decode()


# ---------------------------------------------------------------- 各阶段

def stage_function(args):
    print("[1/2] 部署函数 {}".format(args.name))
    b64 = build_zip_base64(args.src)

    existing = tccli_optional(
        args.region, "scf", "GetFunction",
        FunctionName=args.name, Namespace=args.namespace,
    )

    if "_error" in existing:
        tccli(
            args.region, "scf", "CreateFunction",
            FunctionName=args.name,
            Type=args.function_type,
            Runtime=args.runtime,
            Handler=args.handler,
            MemorySize=args.memory,
            Timeout=args.timeout,
            Namespace=args.namespace,
            Code={"ZipFile": b64},
        )
        print("  ✓ 函数已创建")
    else:
        tccli(
            args.region, "scf", "UpdateFunctionCode",
            FunctionName=args.name,
            Handler=args.handler,
            Namespace=args.namespace,
            Code={"ZipFile": b64},
        )
        print("  ✓ 函数代码已更新")


def stage_url(args):
    """开通函数 URL，只开内网。幂等：已存在则只做现状核对，不做破坏性重建。"""
    print("[2/2] 开通内网函数 URL（EnableExtranet=false）")

    existing = _http_triggers(args)
    if existing:
        for trig in existing:
            desc = trig.get("TriggerDesc") or ""
            if isinstance(desc, str):
                try:
                    desc = json.loads(desc)
                except ValueError:
                    desc = {}
            net = desc.get("NetConfig") or {}
            print("  已存在 http 触发器：{}".format(trig.get("TriggerName")))
            print("    内网={}  公网={}  AuthType={}  Qualifier={}".format(
                net.get("EnableIntranet"), net.get("EnableExtranet"),
                desc.get("AuthType"), trig.get("Qualifier")))
            if net.get("EnableExtranet"):
                print("    ⚠ 公网端点开着。UpdateTrigger 文档写明只支持 timer/ckafka，")
                print("      要关公网只能删掉触发器重建 —— 重建后内网 URL 的 id 会变，")
                print("      任何指向旧 URL 的网关服务上游必须同步改（见 skill tse-gateway-ops）。")
        show_url(args)
        return

    desc = {"AuthType": args.auth_type,
            "NetConfig": {"EnableIntranet": True, "EnableExtranet": False}}
    incoming = args.trigger_name or "{}-url".format(args.name)
    kwargs = dict(FunctionName=args.name, TriggerName=incoming, Type="http",
                  Namespace=args.namespace, Enable="OPEN",
                  TriggerDesc=json.dumps(desc))
    if args.qualifier:
        kwargs["Qualifier"] = args.qualifier
    tccli(args.region, "scf", "CreateTrigger", **kwargs)
    print("  ✓ 函数 URL 已创建（仅内网）")
    print("  注意：http 触发器的真实名称由 SCF 生成（内网 URL 里那段 id），"
          "不是传入的 '{}'。".format(incoming))
    show_url(args)


def show_url(args):
    print("[i] 查询函数 URL")
    resp = tccli(
        args.region, "scf", "ListTriggers",
        FunctionName=args.name, Namespace=args.namespace,
    )
    triggers = resp.get("Triggers") or []
    for trig in triggers:
        if trig.get("Type") != "http":
            continue
        desc = trig.get("TriggerDesc")
        if isinstance(desc, str):
            try:
                desc = json.loads(desc)
            except ValueError:
                desc = {}
        print("  触发器: {}".format(trig.get("TriggerName")))
        print("  TriggerDesc: {}".format(json.dumps(desc, ensure_ascii=False)))
    print("  提示：内网端点形如 https://<url-id>.in.<region>.tencentscf.com")
    print("        本地开发机（公网）访问不了，需从同 VPC 内 CVM 发起。")


# ---------------------------------------------------------------- 版本管理
#
# 两段式的核心事实（都经过实测或官方文档核对）：
#   1. upload 只改 $LATEST —— 可覆盖、无版本号、不产生制品。
#   2. publish(PublishVersion) 把当前 $LATEST 冻结成**自增整数版本**（1,2,3...）。
#      版本号**不可指定**，所以 semver 只能写进 Description 做映射。
#   3. 前两步都不改变线上流量。真正切流量的动作是：
#      - 把触发器（函数 URL）的 Qualifier 指向别名/版本
#      - 或把网关服务的 ScfLambdaQualifier 指过去（网关侧见 skill tse-gateway-ops）
#   4. 触发器 Qualifier 一旦不是 $LATEST，upload 就自动变成"安全的预热"，不再直接上线。

def _find_bump():
    """定位 bump-my-version。常见落点在 miniforge/homebrew，不一定在 PATH 里。"""
    env_bin = os.environ.get("BUMP_BIN")
    if env_bin and os.access(env_bin, os.X_OK):
        return env_bin
    found = shutil.which("bump-my-version")
    if found:
        return found
    for root in ("/opt/homebrew/Caskroom/miniforge/base/bin",
                 "/opt/homebrew/bin", "/usr/local/bin",
                 os.path.expanduser("~/.local/bin")):
        cand = os.path.join(root, "bump-my-version")
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


BUMP = _find_bump()


def read_semver(src_dir):
    """读 semver：优先 VERSION 文件，其次 index.py 里的 __version__。"""
    if src_dir:
        vf = os.path.join(src_dir, "VERSION")
        if os.path.isfile(vf):
            with open(vf, encoding="utf-8") as fh:
                text = fh.read().strip()
            if text:
                return text
        py = os.path.join(src_dir, "index.py")
        if os.path.isfile(py):
            with open(py, encoding="utf-8") as fh:
                match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', fh.read())
            if match:
                return match.group(1)
    return None


def _git_sha(src_dir):
    """拿短 git sha，失败返回 None（不是 git 仓库很正常，不当错误）。"""
    try:
        proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=src_dir or ".", capture_output=True, text=True)
    except (OSError, FileNotFoundError):
        return None
    sha = (proc.stdout or "").strip()
    return sha if proc.returncode == 0 and sha else None


def stage_bump(args):
    """只改本地版本号文件，不碰云。"""
    if not BUMP:
        raise RuntimeError(
            "找不到 bump-my-version。安装：pip install bump-my-version，"
            "或用 BUMP_BIN=/path/to/bump-my-version 指定路径。"
        )
    if not os.path.isfile(os.path.join(args.src, ".bumpversion.toml")):
        raise RuntimeError(
            "源码目录缺少 .bumpversion.toml：{}\n"
            "  可从 skill 的 templates/ 复制一份再改文件名。".format(args.src)
        )

    before = read_semver(args.src)
    cmd = [BUMP, "bump", args.bump_part, "--no-commit", "--no-tag"]
    if args.dry_run:
        cmd += ["--dry-run", "-v"]
    print("[bump] {} {}".format(" ".join(cmd), "(cwd={})".format(args.src)))
    proc = subprocess.run(cmd, cwd=args.src, capture_output=True, text=True)
    for line in ((proc.stdout or "") + (proc.stderr or "")).splitlines():
        if line.strip():
            print("  " + line.strip())

    after = read_semver(args.src)
    if args.dry_run:
        print("  [dry-run] 文件未改动，仍为 {}".format(after))
        return after
    if proc.returncode != 0:
        raise RuntimeError("bump-my-version 退出码 {}".format(proc.returncode))
    print("  ✓ 版本 {} -> {}".format(before, after))
    return after


def build_zip_to_file(src_dir, out_path):
    """把源码目录打成 zip 落盘，返回 (路径, 字节数, sha256)。"""
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in sorted(files):
                if name in SKIP_FILES or name.endswith(SKIP_EXTS):
                    continue
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, src_dir))
                count += 1

    if count == 0:
        raise RuntimeError("源码目录为空：{}".format(src_dir))

    size = os.path.getsize(out_path)
    with open(out_path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("  打包 {} 个文件 -> {}".format(count, out_path))
    print("  大小 {} 字节  sha256 {}".format(size, digest[:16] + "…"))
    return out_path, size, digest


def _zip_path(args):
    """把 --src / --zip / --package-out 解析成一个待上传的 zip 文件。"""
    if args.zip_file:
        if not os.path.isfile(args.zip_file):
            raise RuntimeError("--zip 指定的文件不存在：{}".format(args.zip_file))
        size = os.path.getsize(args.zip_file)
        with open(args.zip_file, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        print("  使用现成 zip：{} ({} 字节)".format(args.zip_file, size))
        return args.zip_file, size, digest

    semver = read_semver(args.src) or "0.0.0"
    # 默认落在 <src>/dist，而不是 CWD —— 否则从不同目录跑会把产物散到各处
    dist_dir = args.dist_dir or os.path.join(args.src, "dist")
    out = args.package_out or os.path.join(
        dist_dir, "{}-{}.zip".format(args.name, semver))
    return build_zip_to_file(args.src, out)


def stage_package(args):
    """只打包，不部署。产物可留档、送审、或交给 CI 上传。"""
    print("[package] 打包（不碰云）")
    _zip_path(args)
    print("  ✓ 产物已生成，可用 --stage upload --zip <该文件> 上传")


def stage_upload(args):
    """上传代码：只更新 $LATEST，不发布版本。"""
    print("[upload] 上传代码到 $LATEST（不发布版本，线上流量不受影响）")
    zip_path, size, digest = _zip_path(args)

    # 上限：顶层 ZipFile 参数 20MB；Code.ZipFile 50MB；解压后总大小 500MB。
    if size > 50 * 1024 * 1024:
        raise RuntimeError(
            "zip {} 字节 > 50MB（Code.ZipFile 上限）。请改用 "
            "--cos-bucket/--cos-object 走 COS（同时需传 CodeSource=Cos）。".format(size))
    if size > 20 * 1024 * 1024:
        print("  ⚠ zip 超过 20MB：顶层 ZipFile 参数上限是 20MB，Code.ZipFile 是 50MB。"
              "本脚本走 Code.ZipFile，但建议 >20MB 时改走 COS 并实测。")

    params = {"FunctionName": args.name, "Namespace": args.namespace}
    if args.cos_bucket and args.cos_object:
        params.update({
            "CodeSource": "Cos",
            "CosBucketName": args.cos_bucket,
            "CosObjectName": args.cos_object,
            "CosBucketRegion": args.cos_region or args.region,
            "Handler": args.handler,
        })
        print("  走 COS：{}/{} @{}".format(args.cos_bucket, args.cos_object,
                                          args.cos_region or args.region))
    else:
        with open(zip_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        params["Code"] = {"ZipFile": b64}
        params["Handler"] = args.handler
        print("  内联 base64 {} 字节（原始 zip {} 字节）".format(len(b64), size))

    existing = tccli_optional(args.region, "scf", "GetFunction",
                              FunctionName=args.name, Namespace=args.namespace)
    if "_error" in existing:
        print("  函数不存在，改为创建")
        tccli(args.region, "scf", "CreateFunction",
              FunctionName=args.name, Type=args.function_type, Runtime=args.runtime,
              MemorySize=args.memory, Timeout=args.timeout, **params)
        print("  ✓ 函数已创建（$LATEST）")
    else:
        tccli(args.region, "scf", "UpdateFunctionCode", **params)
        print("  ✓ 代码已上传到 $LATEST")
    _wait_active(args)
    print("  注意：$LATEST 可被下次 upload 覆盖，未产生版本号。"
          "要留档/可回滚，接着跑 --stage publish。")


def _bind_alias(args, alias, version):
    """别名指向版本：存在则更新，不存在则创建。

    必须先等函数回到 Active —— 刚 PublishVersion 完就改别名会收到
    FailedOperation「当前函数状态无法进行此操作，请在函数状态正常时重试」。
    """
    _wait_active(args)

    exists = tccli_optional(args.region, "scf", "GetAlias",
                            FunctionName=args.name, Name=alias, Namespace=args.namespace)
    if "_error" in exists:
        tccli(args.region, "scf", "CreateAlias",
              FunctionName=args.name, Name=alias, FunctionVersion=version,
              Namespace=args.namespace, Description="deploy.py")
        print("  ✓ 别名 {} 已创建 -> 版本 {}".format(alias, version))
    else:
        tccli(args.region, "scf", "UpdateAlias",
              FunctionName=args.name, Name=alias, FunctionVersion=version,
              Namespace=args.namespace, Description="deploy.py")
        print("  ✓ 别名 {} 已更新 -> 版本 {}".format(alias, version))


def _wait_active(args, timeout=40):
    """等函数状态回到 Active。

    代码更新是异步的：UpdateFunctionCode 返回后立刻 PublishVersion 有可能被拒。
    官方没有承诺同步可见，所以发布前先轮询 Status。
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = tccli_optional(args.region, "scf", "GetFunction",
                              FunctionName=args.name, Namespace=args.namespace)
        last = resp.get("Status") or resp.get("_error") or "(unknown)"
        if last == "Active":
            return True
        print("  … 函数状态 {}，等待更新落地".format(last))
        time.sleep(2)
    print("  ⚠ 等 {}s 后状态仍是 {}，仍尝试发布".format(timeout, last))
    return False


def stage_publish(args):
    """把当前 $LATEST 冻结成不可变版本号，并（可选）把别名指过去。"""
    _wait_active(args)

    semver = args.version or read_semver(args.src)
    desc = args.description
    if not desc:
        parts = []
        if semver:
            parts.append("semver={}".format(semver))
        sha = _git_sha(args.src)
        if sha:
            parts.append("sha={}".format(sha))
        desc = " ".join(parts)

    print("[publish] 发布版本 Description={!r}".format(desc))
    resp = tccli(args.region, "scf", "PublishVersion",
                 FunctionName=args.name, Namespace=args.namespace,
                 Description=desc or None)
    version = str(resp.get("FunctionVersion") or "")
    if not version:
        raise RuntimeError("未能从返回解析 FunctionVersion：{}".format(json.dumps(resp, ensure_ascii=False)))

    print("  ✓ 已发布 SCF 版本 {}{}".format(
        version, "  (semver={})".format(semver) if semver else ""))
    print("  版本号由 SCF 自增分配，无法指定；semver 存在 Description 里做映射。")

    if args.alias:
        _bind_alias(args, args.alias, version)

    print("  ⚠ 至此线上流量仍未改变。切流量靠改触发器 Qualifier"
          "（或网关服务的 ScfLambdaQualifier）：")
    print("     python3 deploy.py --stage qualifier --name {} --qualifier {}".format(
        args.name, args.alias or version))
    return version


def stage_release(args):
    """一条命令走完 bump -> package -> upload -> publish。"""
    if args.bump_part != "none":
        stage_bump(args)
    stage_package(args)
    stage_upload(args)
    return stage_publish(args)


def _http_triggers(args):
    resp = tccli(args.region, "scf", "ListTriggers",
                 FunctionName=args.name, Namespace=args.namespace)
    return [t for t in (resp.get("Triggers") or []) if t.get("Type") == "http"]


def stage_versions(args):
    """列 SCF 版本与别名，形成 semver <-> 版本号 的映射视图。"""
    print("[versions] {} / {} 的版本与别名".format(args.region, args.name))
    resp = tccli(args.region, "scf", "ListVersionByFunction",
                 FunctionName=args.name, Namespace=args.namespace, Limit=50)
    versions = resp.get("Versions") or []
    print("  SCF 版本共 {} 个".format(resp.get("TotalCount", len(versions))))
    for v in versions:
        print("    v{:<8} {:<34} {}".format(
            str(v.get("Version")), v.get("Description") or "-", v.get("ModTime") or ""))

    aliases = tccli_optional(args.region, "scf", "ListAliases",
                             FunctionName=args.name, Namespace=args.namespace)
    print("  别名：")
    for a in (aliases.get("Aliases") or []):
        extra = ""
        rc = a.get("RoutingConfig") or {}
        weights = rc.get("AdditionalVersionWeights") or []
        if weights:
            extra = "  灰度=" + ",".join(
                "{}:{}".format(w.get("Version"), w.get("Weight")) for w in weights)
        print("    {:<10} -> {:<8}{}".format(a.get("Name"), a.get("FunctionVersion"), extra))

    trigs = _http_triggers(args)
    print("  函数 URL 触发器 Qualifier（决定线上跑哪个版本）：")
    for t in trigs:
        print("    {:<14} Qualifier={:<10} {}".format(
            t.get("TriggerName"), t.get("Qualifier"),
            "← 线上跟随 $LATEST，upload 即上线" if t.get("Qualifier") == "$LATEST" else ""))


def stage_qualifier(args):
    """把函数 URL 触发器绑到别名或版本号。

    实测结论：UpdateTrigger 对 http 触发器无效（报 ResourceNotFound，官方文档也写明
    只支持 timer/ckafka），所以只能**删除 + 重建**。代价是内网 URL 的 id 会变，
    必须同步更新所有指向它的网关服务 —— 跨边界动作，见 skill `tse-gateway-ops`。
    """
    if not args.qualifier:
        raise RuntimeError("--qualifier 必填，如 prod 或版本号 2")

    trigs = _http_triggers(args)
    if not trigs:
        raise RuntimeError("该函数没有 http 触发器（函数 URL）。先跑 --stage url。")
    if len(trigs) > 1:
        raise RuntimeError("该函数有 {} 个 http 触发器，重建会影响全部，请先手工清理：{}".format(
            len(trigs), ", ".join(t.get("TriggerName") or "" for t in trigs)))

    trig = trigs[0]
    name = trig.get("TriggerName")
    old_q = trig.get("Qualifier")
    desc = trig.get("TriggerDesc") or ""
    if isinstance(desc, str):
        try:
            desc = json.loads(desc)
        except ValueError:
            desc = {}
    net = desc.get("NetConfig") or {}

    print("[qualifier] 触发器 {}: {} -> {}（http 触发器只能删除重建）".format(
        name, old_q, args.qualifier))

    rebuild = {
        "AuthType": desc.get("AuthType") or args.auth_type,
        "NetConfig": {
            "EnableIntranet": bool(net.get("EnableIntranet", True)),
            "EnableExtranet": bool(net.get("EnableExtranet", False)),
        },
    }
    if (desc.get("CorsConfig") or {}).get("Enable"):
        rebuild["CorsConfig"] = desc["CorsConfig"]

    tccli(args.region, "scf", "DeleteTrigger",
          FunctionName=args.name, TriggerName=name, Type="http", Namespace=args.namespace)
    resp = tccli(args.region, "scf", "CreateTrigger",
                 FunctionName=args.name,
                 TriggerName=args.trigger_name or "{}-url".format(args.name),
                 Type="http", Namespace=args.namespace, Enable="OPEN",
                 Qualifier=args.qualifier,
                 TriggerDesc=json.dumps(rebuild, ensure_ascii=False))

    info = resp.get("TriggerInfo") or resp
    new_desc = info.get("TriggerDesc") or "{}"
    if isinstance(new_desc, str):
        try:
            new_desc = json.loads(new_desc)
        except ValueError:
            new_desc = {}
    new_net = new_desc.get("NetConfig") or {}
    new_url = new_net.get("IntranetUrl") or ""
    print("  ✓ 新触发器 {}  Qualifier={}".format(info.get("TriggerName"), info.get("Qualifier")))
    print("  ⚠ 内网 URL 已变，旧 URL 立即失效：{}".format(new_url))

    host = new_url.replace("https://", "").replace("http://", "").rstrip("/")
    if host:
        print()
        print("  ⚠ 破坏性跨边界动作：任何上游指向旧 URL 的 TSE 网关服务都会 503。")
        print("     用 skill `tse-gateway-ops` 把上游切到新地址：")
        print("       python3 gateway.py --stage upstream --region {} \\".format(
            args.region or "<region>"))
        print("         --gateway-id <gateway-id> --service-id <service-id> \\")
        print("         --name {} --intranet-url 'https://{}'".format(args.name, host))
        print("     或用它列出受影响的服务：python3 gateway.py --stage show \\")
        print("         --gateway-id <gateway-id> --grep {}".format(args.name))


def stage_alias(args):
    """只移动别名指向 —— 流量切换的最小动作，不重建任何东西。"""
    if not args.alias or not args.to_version:
        raise RuntimeError("--alias 与 --to-version 必填")
    print("[alias] {} -> 版本 {}".format(args.alias, args.to_version))
    _bind_alias(args, args.alias, args.to_version)
    print("  别名绑定立即生效；回滚就是把它指回上一个版本号。")


# ---------------------------------------------------------------- 入口

def main():
    p = argparse.ArgumentParser(description="SCF 云函数交付与版本管理")
    p.add_argument("--stage", required=True,
                   choices=["function", "url", "show-url",
                            "bump", "package", "upload", "publish", "release",
                            "versions", "qualifier", "alias"],
                   help="function/url=首次部署；"
                        "bump/package/upload/publish/release=迭代发布；"
                        "versions/qualifier/alias=版本与流量切换")
    p.add_argument("--region", default=None,
                   help="地域。省略则用 tccli configure 里的默认地域")
    p.add_argument("--name", required=True, help="函数名")
    p.add_argument("--src", default="./pkg", help="函数源码目录")
    p.add_argument("--namespace", default="default")
    p.add_argument("--runtime", default="Python3.10")
    p.add_argument("--handler", default="index.main_handler")
    p.add_argument("--function-type", default="Event", help="Event=事件函数, HTTP=Web函数")
    p.add_argument("--memory", type=int, default=128)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--auth-type", default="NONE", help="NONE 或 CAM")
    p.add_argument("--trigger-name", default=None,
                   help="http 触发器名。函数 URL 的触发器名由 SCF 自动生成，"
                        "有多个触发器时必须显式指定")

    # ---- 版本与制品 ----
    p.add_argument("--bump-part", default="patch",
                   choices=["major", "minor", "patch", "none"],
                   help="bump 哪一段；none=跳过 bump（release 时用）")
    p.add_argument("--dry-run", action="store_true", help="bump 只预演不改文件")
    p.add_argument("--dist-dir", default=None,
                   help="zip 产物输出目录，默认 <src>/dist（不是 CWD）")
    p.add_argument("--zip", dest="zip_file", help="直接用现成 zip 上传，跳过打包")
    p.add_argument("--package-out", help="指定 zip 输出路径")
    p.add_argument("--version", help="覆盖 semver（默认读 VERSION / index.py）")
    p.add_argument("--description", help="发布版本的 Description；默认 semver+git sha")
    p.add_argument("--alias", help="发布后把别名指向新版本，如 prod")
    p.add_argument("--qualifier", help="触发器要绑定的版本号或别名，如 prod（会删除重建触发器）")
    p.add_argument("--to-version", help="--stage alias 时别名要改指向的版本号")
    p.add_argument("--cos-bucket", help="zip >50MB 时走 COS 上传")
    p.add_argument("--cos-object", help="COS 对象路径，以 / 开头")
    p.add_argument("--cos-region", help="COS 地域，默认同 --region")

    # ---- 网关相关参数已移除 ----
    # 服务/路由的创建与上游切换属于 skill `tse-gateway-ops` 的职责。
    # 这里刻意不留 --gateway-id 之类的入口，避免两个 skill 的职责互相渗透。

    args = p.parse_args()

    try:
        if args.stage == "function":
            stage_function(args)
        elif args.stage == "url":
            stage_url(args)
        elif args.stage == "show-url":
            show_url(args)
        elif args.stage == "bump":
            stage_bump(args)
        elif args.stage == "package":
            stage_package(args)
        elif args.stage == "upload":
            stage_upload(args)
        elif args.stage == "publish":
            stage_publish(args)
        elif args.stage == "release":
            stage_release(args)
        elif args.stage == "versions":
            stage_versions(args)
        elif args.stage == "qualifier":
            stage_qualifier(args)
        elif args.stage == "alias":
            stage_alias(args)
    except RuntimeError as exc:
        print("\n✗ 失败：{}".format(exc), file=sys.stderr)
        return 1

    if args.stage not in ("bump", "package"):
        print("\n完成。提醒：内网链路必须在 VPC 内验证，本地 curl 超时属正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
