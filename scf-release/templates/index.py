# -*- coding: utf-8 -*-
"""SCF 事件函数脚手架 —— 返回标准集成响应结构体。

适配两条调用路径：
  1) 函数 URL（CreateTrigger Type=http）
  2) TSE 云原生网关（UpstreamType=Scf）

部署：Handler 配为 index.main_handler，Runtime 用 Python3.10。

版本：__version__ 由 bump-my-version 维护（见同目录 .bumpversion.toml）。
     这一行的**写法是 bump 的匹配锚点**，改了格式 bump 就找不到。
     它同时进响应体和响应头，用来证明线上跑的到底是哪个版本。
"""

import json

__version__ = "0.1.0"


def main_handler(event, context):
    """事件函数入口。

    event 字段（函数 URL / 网关调用时）：
        body        str   请求体原文（JSON 需自行反序列化）
        headers     dict  请求头
        httpMethod  str   请求方法
        path        str   请求路径
        queryString dict  查询参数

    注意：比 API 网关触发器少了 requestContext / pathParameters /
         headerParameters / isBase64Encoded 等字段，不要读这些键。
    """
    http_method = event.get("httpMethod", "GET")
    path = event.get("path", "/")
    query = event.get("queryString") or {}

    raw_body = event.get("body") or ""
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except (ValueError, TypeError):
        payload = {"_raw": raw_body}

    result = {
        "ok": True,
        "version": __version__,
        "method": http_method,
        "path": path,
        "query": query,
        "received": payload,
        "request_id": _request_id(context),
    }
    return _resp(200, result)


def _request_id(context):
    """兼容 context 为对象或 dict 两种形态。"""
    rid = getattr(context, "request_id", None)
    if rid is None and isinstance(context, dict):
        rid = context.get("request_id")
    return rid


def _resp(status_code, data):
    """标准集成响应结构体 —— 缺了它，网关/URL 会把 JSON 当纯文本透传。"""
    return {
        "isBase64Encoded": False,
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "X-Scf-Skill": "scf-release",
            "X-Scf-Version": __version__,
        },
        "body": json.dumps(data, ensure_ascii=False),
    }
