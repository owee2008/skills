#!/usr/bin/env python3
"""Apifox 环境变量鉴权、定义上传CLI桥接及单次OpenAPI导入；默认预览，不重试写请求。"""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

PUBLIC_BASE = "https://api.apifox.com"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
READ_COMMANDS = {("project", "list"), ("project", "get"), ("folder", "list"),
                 ("endpoint", "list"), ("endpoint", "get"), ("branch", "list"),
                 ("test-case", "list"), ("test-case", "get"), ("test-case", "category"),
                 ("test-scenario", "list"), ("test-scenario", "get")}
LOCAL_COMMANDS = {("cli-schema", "list"), ("cli-schema", "get"), ("cli-schema", "validate")}
FILE_WRITE_SCHEMAS = {(resource, action): resource + "-" + action
                      for resource in ("endpoint", "test-case", "test-scenario", "folder")
                      for action in ("create", "update")}
WRITE_COMMANDS = set(FILE_WRITE_SCHEMAS) | {("test-scenario", "import-steps"),
                                           ("branch", "create"), ("branch", "pick-to")}


class InputError(ValueError):
    """可直接反馈给操作者的固定诊断，不包含凭据或请求内容。"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """写入或鉴权请求遇到重定向就返回结果，不把令牌自动转发到另一个地址。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def token_from_env():
    """只读取环境中的令牌；缺失不查找其他凭据来源。"""
    token = os.environ.get("APIFOX_ACCESS_TOKEN", "").strip()
    if not token or "\r" in token or "\n" in token:
        raise InputError("请在执行环境配置有效的 APIFOX_ACCESS_TOKEN")
    return token


def payload_for(args):
    """核对授权接口清单；例如仅授权POST /x时，带GET /y的文件会被拒绝。"""
    if args.project_id <= 0 or args.folder_id < 0:
        raise InputError("project-id必须大于0；folder-id必须显式指定，0表示根目录")
    doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not str(doc.get("openapi", "")).startswith("3."):
        raise InputError("请提供已打包的 OpenAPI 3 JSON 文件")
    paths = doc.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise InputError("OpenAPI缺少非空paths")
    actual = set()
    for path, item in paths.items():
        if not path.startswith("/") or not isinstance(item, dict):
            raise InputError("接口路径或path item不合法")
        actual.update((method.upper(), path) for method in item if method in HTTP_METHODS)
    expected = {(method.upper(), path) for method, path in args.endpoint}
    if not actual or actual != expected:
        raise InputError("OpenAPI的method/path与--endpoint授权清单不一致")
    def local_refs(value):
        if isinstance(value, dict):
            ref = value.get("$ref")
            if ref is not None:
                if not isinstance(ref, str) or not ref.startswith("#/"):
                    raise InputError("外部$ref须先打包为本地引用")
                target = doc
                for part in ref[2:].split("/"):
                    key = part.replace("~1", "/").replace("~0", "~")
                    target = target[int(key)] if isinstance(target, list) else target[key]
            for child in value.values():
                local_refs(child)
        elif isinstance(value, list):
            for child in value:
                local_refs(child)
    local_refs(doc)
    payload = {"input": json.dumps(doc, ensure_ascii=False), "options": {
        "targetEndpointFolderId": args.folder_id,
        "endpointOverwriteBehavior": "OVERWRITE_EXISTING",
        "schemaOverwriteBehavior": "KEEP_EXISTING",
        "updateFolderOfChangedEndpoint": False, "prependBasePath": False}}
    return payload, sorted(actual)


def import_once(args):
    """预览无网络/凭据读取；--apply只发一次导入请求，所有结果都要求独立回查。"""
    payload, endpoints = payload_for(args)
    summary = {"projectId": args.project_id, "folderId": args.folder_id, "endpoints": endpoints}
    if not args.apply:
        return {"status": "PREVIEW", **summary, "options": payload["options"]}
    token = token_from_env()
    request = urllib.request.Request(
        f"{PUBLIC_BASE}/v1/projects/{args.project_id}/import-openapi?locale=zh-CN",
        data=json.dumps(payload, ensure_ascii=False).encode(), method="POST",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "X-Apifox-Api-Version": "2024-03-28"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=45) as response:
            data = json.load(response)
            counters = data.get("data", {}).get("counters")
            if not isinstance(counters, dict):
                return {"status": "RESULT_UNKNOWN", **summary, "requiresReadback": True}
            # 仅输出数字计数，避免服务端错误包络回显任何凭据或上传内容。
            counts = {key: value for key, value in counters.items() if type(value) is int}
            status = "IMPORT_PARTIAL" if any(value > 0 for key, value in counts.items() if key.endswith("Failed")) else "IMPORT_RESPONSE"
            return {"status": status, **summary, "counters": counts, "requiresReadback": True}
    except urllib.error.HTTPError as error:
        return {"status": "HTTP_ERROR", **summary, "httpStatus": error.code, "requiresReadback": True}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError):
        return {"status": "RESULT_UNKNOWN", **summary, "requiresReadback": True}


def option(command, flag):
    """读取唯一的目标选项；同时支持--project 123和--project=123，重复目标直接拒绝。"""
    values = []
    for index, arg in enumerate(command):
        if arg == flag:
            values.append(command[index + 1] if index + 1 < len(command) else "")
        elif arg.startswith(flag + "="):
            values.append(arg.split("=", 1)[1])
    if len(values) > 1:
        raise InputError("目标选项重复：" + flag)
    return values[0] if values else None


def write_plan(command):
    """限定定义写入的目标与输入；例如test-case create必须明确项目、分支及JSON文件。"""
    key = tuple(command[:2])
    project = option(command, "--project")
    if not project or not project.isdecimal() or int(project) <= 0:
        raise InputError("定义写入必须显式指定有效--project")
    if command[0] == "branch":
        if option(command, "--file") or "--protected" in command:
            raise InputError("AI分支创建/引用不接受权限配置文件或保护设置")
        if option(command, "--type") != "ai" or not option(command, "--from"):
            raise InputError("分支写入仅支持显式来源的AI分支")
        if not option(command, "--name" if command[1] == "create" else "--to"):
            raise InputError("必须显式指定AI目标分支")
    elif not option(command, "--branch"):
        raise InputError("定义写入必须显式指定--branch，避免误写默认分支")
    if command[1] in ("update", "import-steps"):
        identifier = command[2] if len(command) > 2 else ""
        if not identifier.isdecimal() or int(identifier) <= 0:
            raise InputError("更新或关联必须使用已回查的真实资源ID，不能使用占位ID")
    schema = FILE_WRITE_SCHEMAS.get(key)
    filename = option(command, "--file")
    if schema:
        if not filename:
            raise InputError("该定义写入必须提供--file")
        data = json.loads(Path(filename).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise InputError("定义文件必须是JSON对象")
        if "projectId" in data and str(data["projectId"]) != project:
            raise InputError("定义文件projectId与--project不一致")
    if key == ("test-scenario", "import-steps"):
        source = option(command, "--source")
        if source not in ("endpoint", "test-case", "test-scenario"):
            raise InputError("步骤导入必须明确--source")
        if source in ("endpoint", "test-case") and not option(command, "--ids"):
            raise InputError("步骤导入必须明确--ids")
        if source in ("endpoint", "test-case") and any(
                not value.isdecimal() or int(value) <= 0 for value in option(command, "--ids").split(",")):
            raise InputError("--ids必须来自创建/查询结果，不能使用占位ID")
        if source == "test-case" and not option(command, "--endpoint"):
            raise InputError("单接口用例导入必须明确--endpoint")
    return {"projectId": int(project), "branch": option(command, "--branch") or option(command, "--name") or option(command, "--to"),
            "schemaKey": schema, "file": filename, "command": command}


def cli_entry(args):
    """复用已安装/缓存的官方CLI，脚本本身不安装软件或持久化登录。"""
    candidates = [Path(args.cli_js)] if args.cli_js else []
    installed = shutil.which("apifox")
    if not candidates and installed:
        candidates = [Path(installed).resolve()]
    if not candidates:
        candidates = sorted((Path.home()/".npm/_npx").glob("*/node_modules/apifox-cli/bin/cli.js"),
                            key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates or not candidates[0].is_file() or not shutil.which("node"):
        raise InputError("缺少Node或官方CLI；先移除令牌环境变量再缓存apifox-cli，参见SKILL.md")
    return str(candidates[0])


def cli_json(text):
    """兼容CLI在JSON前打印创建提示；截断响应不冒充完整结果。"""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    for match in re.finditer(r"(?m)^\{", text):
        try:
            data, _ = json.JSONDecoder().raw_decode(text[match.start():])
            if isinstance(data, dict) and "success" in data:
                return data
        except ValueError:
            pass
    raise InputError("CLI未返回完整JSON；只重试回查，不能据此重试写入")


def invoke_cli(entry, command, token=None):
    """令牌仅进子进程环境；同步刷新长JSON，并保留CLI原有退出及权限检查。"""
    program = ("const p=process.argv[2],a=JSON.parse(process.argv[1]);"
               "const h=process.stdout._handle;if(h&&typeof h.setBlocking==='function')h.setBlocking(true);"
               "const t=process.env.APIFOX_ACCESS_TOKEN;delete process.env.APIFOX_ACCESS_TOKEN;"
               "process.argv=[process.argv[0],p,...a,...(t?['--access-token',t]:[])];require(p);")
    env = dict(os.environ)
    env.pop("APIFOX_ACCESS_TOKEN", None)
    if token:
        env["APIFOX_ACCESS_TOKEN"] = token
    result = subprocess.run([shutil.which("node"), "-e", program, json.dumps(command), entry], env=env, capture_output=True, text=True, timeout=60)
    return result.returncode, cli_json(result.stdout.replace(token, "<redacted>") if token else result.stdout)


def run_cli(args):
    """只读直接执行；定义写入默认预览，--apply校验后只写一次，永不运行或删除测试。"""
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    key = tuple(command[:2])
    if key not in READ_COMMANDS | LOCAL_COMMANDS | WRITE_COMMANDS or any(arg.startswith("--access-token") for arg in command):
        raise InputError("cli仅支持发现、回查和定义上传；不支持run/delete/merge/login或命令行令牌")
    writing = key in WRITE_COMMANDS
    plan = write_plan(command) if writing else None
    if writing and not args.apply:
        return {"status": "PREVIEW", **plan, "testsExecuted": False}
    entry = cli_entry(args)
    token = None if key in LOCAL_COMMANDS else token_from_env()
    if writing and plan["schemaKey"]:
        code, validation = invoke_cli(entry, ["cli-schema", "validate", plan["schemaKey"], "--file", plan["file"]])
        if code or validation.get("success") is not True or validation.get("data", {}).get("valid") is not True:
            return {"status": "VALIDATION_FAILED", "validation": validation}
    try:
        code, data = invoke_cli(entry, command, token)
    except (InputError, subprocess.TimeoutExpired, OSError):
        if writing:
            return {"status": "RESULT_UNKNOWN", "requiresReadback": True, "command": command, "testsExecuted": False}
        raise
    if args.name_contains and isinstance(data.get("data"), list):
        match = args.name_contains.casefold()
        data["data"] = [item for item in data["data"] if match in str(item.get("name", "")).casefold()]
    if writing:
        status = "WRITE_RESPONSE" if data.get("success") is True else "WRITE_REJECTED" if data.get("success") is False else "RESULT_UNKNOWN"
        return {"status": status, "cliExit": code, "result": data, "requiresReadback": True, "testsExecuted": False}
    return {"cliExit": code, "result": data}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    cli = commands.add_parser("cli", help="只读或定义上传；写入默认预览，不执行测试")
    cli.add_argument("--apply", action="store_true", help="执行受限的定义写入，仍不会运行测试")
    cli.add_argument("--cli-js", help="显式指定官方CLI入口，默认复用已安装或缓存版本")
    cli.add_argument("--name-contains", help="按名称过滤只读列表输出，避免大量无关项目占用上下文")
    cli.add_argument("command", nargs=argparse.REMAINDER)
    upload = commands.add_parser("import", help="默认预览；--apply才执行导入")
    upload.add_argument("--project-id", type=int, required=True)
    upload.add_argument("--folder-id", type=int, required=True)
    upload.add_argument("--file", required=True)
    upload.add_argument("--endpoint", nargs=2, action="append", required=True, metavar=("METHOD", "PATH"))
    upload.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if os.environ.get("APIFOX_API_BASE_URL", PUBLIC_BASE).rstrip("/") != PUBLIC_BASE:
            raise InputError("此脚本针对Apifox公有云；私有化地址请先使用已验证的对应读写工具")
        result = import_once(args) if args.action == "import" else run_cli(args)
    except InputError as error:
        print(json.dumps({"status": "INPUT_ERROR", "message": str(error)}, ensure_ascii=False))
        return 1
    except (ValueError, TypeError, KeyError, IndexError, OSError, subprocess.TimeoutExpired):
        # 错误信息固定，不打印可能包含环境变量或进程输出的异常对象。
        print(json.dumps({"status": "INPUT_OR_CONNECTION_ERROR",
                          "hint": "检查目标ID、OpenAPI授权清单、本地引用、APIFOX_ACCESS_TOKEN及官方CLI配置"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get("status") in ("RESULT_UNKNOWN", "HTTP_ERROR", "IMPORT_PARTIAL", "WRITE_REJECTED", "VALIDATION_FAILED") or result.get("cliExit", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
