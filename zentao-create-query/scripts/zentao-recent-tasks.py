#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按人查询「最近」禅道任务 —— 用于快速锁定派工的项目 / 模块 / 工时 / 周期

设计原则：只看最近，不扫全量。
  - 未指定项目时，只扫项目列表里 ID 最大的若干个（最新项目）；
  - 每个项目只取任务列表第一页（禅道默认按最新在前），取前 N 条匹配；
  - 命中 --limit 条即停。

用法:
  zentao-recent-tasks.py <姓名或账号> [选项]

选项:
  --user-text "文本"   自动检测禅道服务（天远/typm、田一/tycd）
  --projects 428,429   只看指定项目（强烈推荐，最快最准）
  --scan 6             未指定项目时，扫描最新 N 个项目（默认 6）
  --per-project 8      每个项目最多取 N 条命中（默认 8）
  --limit 10           总共最多输出 N 条（默认 10）
  -h, --help           帮助

示例:
  ./zentao-recent-tasks.py 周丙龙 --user-text "天远" --projects 428
  ./zentao-recent-tasks.py zhoubinglong --user-text "天远" --scan 8 --limit 15
"""

import sys
import os
import re
import html

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao_common import (
    ZentaoClient,
    ZentaoError,
    VaultError,
)

STATUS_CN = {
    'wait': '未开始', 'doing': '进行中', 'done': '已完成',
    'pause': '已暂停', 'cancel': '已取消', 'closed': '已关闭',
}


def print_usage():
    print(__doc__)


def parse_args(argv):
    person = None
    user_text = None
    projects = []
    scan = 6
    per_project = 8
    limit = 10
    zentao_url = None

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('-h', '--help'):
            print_usage()
            sys.exit(0)
        elif a == '--user-text':
            user_text = argv[i + 1]
            i += 2
            continue
        elif a == '--projects':
            projects = [p.strip() for p in argv[i + 1].split(',') if p.strip()]
            i += 2
            continue
        elif a == '--scan':
            scan = int(argv[i + 1])
            i += 2
            continue
        elif a == '--per-project':
            per_project = int(argv[i + 1])
            i += 2
            continue
        elif a == '--limit':
            limit = int(argv[i + 1])
            i += 2
            continue
        else:
            if person is None:
                person = a
            else:
                zentao_url = a  # 也允许直接给服务 URL
        i += 1

    if not person:
        print("错误: 需要提供姓名或账号")
        print_usage()
        sys.exit(1)

    url = zentao_url or (
        ZentaoClient.detect_service_from_text(user_text) if user_text else None
    )
    return person, url, projects, scan, per_project, limit


def row_text(row_html):
    text = re.sub(r'<[^>]+>', ' ', row_html)
    return html.unescape(re.sub(r'\s+', ' ', text)).strip()


def parse_row(row_html):
    """从任务列表的一行里解析出各字段"""
    ids = re.findall(r'/biz/task-view-(\d+)\.html', row_html)
    if not ids:
        return None
    cells = [row_text(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.S)]
    if not cells:
        return None
    flat = row_text(row_html)
    # 列表页结构大致：ID 优先级 名称 状态 预计 消耗 剩余 进度 截止 创建者 指派给
    nums = re.findall(r'\b(\d+(?:\.\d+)?)\b', flat)
    deadline = ''
    m = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', flat)
    if m:
        deadline = m.group(1)
    else:
        m2 = re.search(r'\b(\d{2}-\d{2})\b', flat)
        if m2:
            deadline = m2.group(1)
    estimate = nums[3] if len(nums) > 3 else ''
    left = nums[5] if len(nums) > 5 else ''
    return {
        'id': ids[0],
        'flat': flat,
        'estimate': estimate,
        'left': left,
        'deadline': deadline,
    }


def main():
    person, zentao_url, projects, scan, per_project, limit = parse_args(sys.argv[1:])

    client = ZentaoClient(zentao_url)
    try:
        client.login_with_available_credentials()
    except VaultError as e:
        print(f"✗ 凭据错误: {e}")
        return 1
    except ZentaoError as e:
        print(f"✗ 禅道错误: {e}")
        return 1

    print(f"禅道服务: {client.base_url}")
    print(f"查询对象: {person}（只扫最近任务，不扫全量）\n")

    # 确定要扫的项目
    if projects:
        targets = [(p, '') for p in projects]
    else:
        all_projects = client.get_projects()
        def pid_key(p):
            try:
                return int(p.get('id'))
            except (TypeError, ValueError):
                return -1
        newest = sorted(all_projects, key=pid_key, reverse=True)[:scan]
        targets = [(str(p.get('id')), p.get('name', '')) for p in newest]
        print(f"未指定项目，扫描最新的 {len(targets)} 个项目："
              + ', '.join(f"{i}({n or ''})" for i, n in targets) + "\n")

    hits = []
    module_cache = {}

    for pid, pname in targets:
        if len(hits) >= limit:
            break
        try:
            resp = client.session.get(
                f"{client.base_url}/biz/project-task-{pid}.html", timeout=40
            )
        except Exception as e:
            print(f"  [项目 {pid}] 拉取失败: {e}")
            continue

        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', resp.text, re.S)
        got = 0
        for r in rows:
            if got >= per_project or len(hits) >= limit:
                break
            if person not in r:
                continue
            parsed = parse_row(r)
            if not parsed:
                continue
            # 取详情以拿到准确的模块 / 预计 / 剩余
            try:
                detail = client.get_task_detail(int(parsed['id']))
            except Exception:
                detail = {}
            rf = detail.get('raw_fields', {})
            module_id = str(detail.get('module') or '')
            if module_id and module_id not in module_cache:
                try:
                    mods = client.get_modules(int(pid))
                    module_cache.update({str(m.get('id')): m.get('name', '') for m in mods})
                except Exception:
                    pass
            status = rf.get('status', '')
            hits.append({
                'id': parsed['id'],
                'name': detail.get('name') or parsed['flat'][:60],
                'project': pid,
                'project_name': pname,
                'module': module_id,
                'module_name': module_cache.get(module_id, ''),
                'estimate': detail.get('estimate') or parsed['estimate'],
                'left': detail.get('left') or parsed['left'],
                'deadline': detail.get('deadline') or parsed['deadline'],
                'status': STATUS_CN.get(status, status),
                'assigned': rf.get('assignedTo', ''),
            })
            got += 1

    if not hits:
        print(f"✗ 未在最近任务中找到「{person}」的记录。")
        print("  建议：用 --projects 指定项目，或加大 --scan / --per-project。")
        return 0

    print(f"最近任务（{len(hits)} 条）：\n")
    print(f"{'ID':<8}{'项目':<8}{'模块':<32}{'预计':<6}{'剩余':<6}{'截止':<12}{'状态':<8}任务名称")
    print("-" * 120)
    for h in hits:
        mod = f"{h['module']} {h['module_name']}".strip()
        print(f"{h['id']:<8}{h['project']:<8}{mod[:30]:<32}"
              f"{str(h['estimate']):<6}{str(h['left']):<6}{str(h['deadline']):<12}"
              f"{h['status']:<8}{h['name'][:60]}")

    # 给出可直接套用的建议
    from collections import Counter
    mods = [f"{h['module']} {h['module_name']}".strip() for h in hits if h['module']]
    ests = [str(h['estimate']) for h in hits if h['estimate']]
    print("\n建议默认值：")
    print(f"  项目        : {hits[0]['project']} {hits[0]['project_name']}")
    if mods:
        top_mod, n = Counter(mods).most_common(1)[0]
        print(f"  模块        : {top_mod}（{n}/{len(hits)} 条命中）")
    if ests:
        top_est, n = Counter(ests).most_common(1)[0]
        print(f"  工时        : {top_est}h（{n}/{len(hits)} 条命中）")
    print(f"  指派账号    : {hits[0]['assigned']}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
