#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建禅道任务；支持单条兼容参数和同项目批量清单。"""

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao_common import (
    ZentaoClient, ZentaoError, ZentaoWriteOutcomeUnknown, VaultError, check_user_permission
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='创建禅道任务')
    parser.add_argument('legacy', nargs='*', metavar='参数', help='兼容：项目ID 任务名 模块ID [负责人 类型 工时 开始 截止]')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--batch-json', help='待预检的批量清单 JSON 文件')
    source.add_argument('--approved-plan', help='预检输出并经用户确认的版本化计划 JSON 文件')
    parser.add_argument('--dry-run', action='store_true', help='只登录和预检，不创建任务')
    parser.add_argument('--user-text', help='用于识别 tycd 或 typm 服务')
    parser.add_argument('--force', action='store_true', help='兼容旧参数；批量模式不需要交互确认')
    parser.add_argument('--wizard', action='store_true', help='启动原交互式向导')
    return parser


def default_dates() -> Dict[str, str]:
    """在实际执行时计算默认日期，避免确认后跨日仍沿用旧日期。"""
    today = date.today()
    return {'begin': str(today - timedelta(days=5)), 'end': str(today + timedelta(days=10))}


def normalize_reference(value: Any) -> str:
    """归一化用户口语名称，例如“我的日志项目”与“我的日志”。"""
    text = re.sub(r'[\s/_\-:：]+', '', str(value).strip().lower())
    for suffix in ('项目', '模块'):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
    return text


def match_reference(value: Any, items: List[Dict[str, Any]], id_key: str, name_key: str) -> List[Dict[str, Any]]:
    """优先按 ID/账号或完整名称匹配，找不到时再返回相关名称。"""
    raw = str(value).strip()
    direct = [item for item in items if str(item.get(id_key, '')).strip() == raw]
    if direct:
        return direct
    needle = normalize_reference(raw)
    keyed = []
    for item in items:
        name = str(item.get(name_key, ''))
        keys = {normalize_reference(name)}
        keys.update(normalize_reference(part) for part in re.split(r'[/：:]', name) if part)
        keyed.append((item, keys))
    exact = [item for item, keys in keyed if needle in keys]
    return exact or [item for item, keys in keyed if any(needle in key or key in needle for key in keys)]


def leaf_modules(modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """名称推断只使用没有下级路径的真实模块。"""
    names = [str(module.get('name', '')).rstrip('/') for module in modules]
    return [module for module in modules if not any(
        other.startswith(f"{str(module.get('name', '')).rstrip('/')}/") for other in names
    )]


def load_batch(path: str, user_text: str = None, require_approved: bool = False) -> Dict[str, Any]:
    """读取并规范化批量清单或版本化批准计划。"""
    try:
        with open(path, encoding='utf-8') as handle:
            batch = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ZentaoError(f'无法读取批量清单: {error}')
    if not isinstance(batch, dict):
        raise ZentaoError('批量清单必须是 JSON 对象')
    if require_approved and (
        batch.get('plan_version') != 1 or batch.get('status') != 'ready' or batch.get('dry_run') is not True
    ):
        raise ZentaoError('批准计划格式无效：需要 dry_run=true、status=ready、plan_version=1')
    project_value = batch.get('project')
    if require_approved:
        project_ref = batch.get('project_id') or (project_value.get('id') if isinstance(project_value, dict) else None)
        if not str(project_ref or '').isdigit():
            raise ZentaoError('批准计划格式无效：project.id 必须是数值 ID')
    else:
        project_ref = batch.get('project_id', project_value)
        if isinstance(project_ref, dict):
            project_ref = project_ref.get('id') or project_ref.get('name')
        if project_ref in (None, ''):
            raise ZentaoError('批量清单必须包含 project_id 或 project')
    if not isinstance(batch.get('tasks'), list) or not batch['tasks']:
        raise ZentaoError('批量清单必须包含非空 tasks 数组')

    dates = default_dates()
    tasks = []
    for index, source in enumerate(batch['tasks'], start=1):
        if not isinstance(source, dict):
            raise ZentaoError(f'第 {index} 条任务必须是对象')
        required = ('name', 'module', 'assigned_to', 'estimate')
        missing = [key for key in required if source.get(key) in (None, '')]
        if missing:
            raise ZentaoError(f'第 {index} 条任务缺少: {", ".join(missing)}')
        if require_approved and not str(source['module']).isdigit():
            raise ZentaoError(f'批准计划格式无效：第 {index} 条任务的 module 必须是数值 ID')
        try:
            task = {
                'name': str(source['name']).strip(),
                'module': int(source['module']) if str(source['module']).isdigit() else str(source['module']).strip(),
                'assigned_to': str(source['assigned_to']).strip(), 'estimate': str(source['estimate']).strip(),
                'task_type': str(source.get('task_type') or 'devel'),
                'begin': str(source.get('begin') or dates['begin']),
                'end': str(source.get('end') or dates['end']), 'desc': str(source.get('desc') or ''),
            }
        except (TypeError, ValueError) as error:
            raise ZentaoError(f'第 {index} 条任务字段格式错误: {error}')
        if not task['name'] or not task['assigned_to'] or float(task['estimate']) <= 0:
            raise ZentaoError(f'第 {index} 条任务名称、负责人和正工时均为必填')
        tasks.append(task)
    normalized_project = int(project_ref) if str(project_ref).isdigit() else str(project_ref).strip()
    service_text = user_text or batch.get('user_text') or batch.get('service', '')
    return {
        'project_id': normalized_project, 'user_text': service_text,
        'approved': require_approved, 'tasks': tasks,
    }


def preflight_batch(client: ZentaoClient, batch: Dict[str, Any]) -> Dict[str, Any]:
    """校验 load_batch 已规范化的任务；此函数绝不写入禅道。"""
    project_ref = batch['project_id']
    if isinstance(project_ref, int):
        project_id = project_ref
    else:
        project_matches = match_reference(project_ref, client.get_projects(), 'id', 'name')
        if len(project_matches) != 1:
            return {
                'service': client.base_url,
                'status': 'needs_confirmation',
                'ambiguities': [{
                    'field': 'project', 'input': project_ref,
                    'candidates': [
                        {'id': int(item['id']), 'name': item.get('name', '')} for item in project_matches
                    ],
                }],
            }
        project_id = int(project_matches[0]['id'])
    project = client.get_project_info(project_id)
    if str(project.get('status', '')).lower() in {'closed', 'done'}:
        raise ZentaoError(f'项目 {project_id} 当前状态不可创建: {project.get("status")}')
    options = client.get_task_creation_options(project_id)
    modules = {int(module['id']): module for module in options['modules']}
    assignees = {item['account']: item for item in options['assignees']}
    if not modules:
        raise ZentaoError(f'项目 {project_id} 没有可用任务模块')
    if not assignees:
        raise ZentaoError(f'项目 {project_id} 的负责人列表不可用')

    approved = batch.get('approved', False)
    confirmed_tasks = []
    ambiguities = []
    for task in batch['tasks']:
        module_ref = task['module']
        module_matches = []
        if isinstance(module_ref, int):
            module = modules.get(module_ref)
        else:
            module_matches = match_reference(module_ref, leaf_modules(options['modules']), 'id', 'name')
            module = module_matches[0] if len(module_matches) == 1 else None
        if not module and approved:
            raise ZentaoError(f'批准计划模块已失效: {module_ref}，请重新预检')
        if not module:
            ambiguities.append({
                'task': task['name'], 'field': 'module', 'input': module_ref,
                'candidates': [
                    {'id': int(item['id']), 'name': item.get('name', '')} for item in module_matches
                ],
            })

        assignee_ref = task['assigned_to']
        if approved:
            assignee = assignees.get(assignee_ref)
            assignee_matches = [assignee] if assignee else []
        else:
            assignee_matches = match_reference(assignee_ref, options['assignees'], 'account', 'name')
            assignee = assignee_matches[0] if len(assignee_matches) == 1 else None
        if not assignee and approved:
            raise ZentaoError(f'批准计划负责人已失效: {assignee_ref}，请重新预检')
        if not assignee:
            ambiguities.append({
                'task': task['name'], 'field': 'assigned_to', 'input': assignee_ref,
                'candidates': [
                    {'account': item['account'], 'name': item.get('name', '')} for item in assignee_matches
                ],
            })
        if module and assignee:
            confirmed_tasks.append({
                **task, 'module': int(module['id']), 'module_name': module['name'],
                'assigned_to': assignee['account'], 'assignee_name': assignee['name'],
            })

    if ambiguities:
        return {
            'service': client.base_url,
            'status': 'needs_confirmation',
            'project': {key: project.get(key) for key in ('id', 'name', 'status')},
            'ambiguities': ambiguities,
        }

    return {
        'plan_version': 1,
        'status': 'ready',
        'service': client.base_url,
        'project': {key: project.get(key) for key in ('id', 'name', 'status')},
        'tasks': confirmed_tasks,
    }


def detail_value(detail: Dict[str, Any], key: str) -> Any:
    """兼容详情顶层或 raw_fields 的同一字段。"""
    return detail.get(key) if detail.get(key) not in (None, '') else (detail.get('raw_fields') or {}).get(key)


def create_and_verify(client: ZentaoClient, project_id: int, task: Dict[str, Any]) -> Dict[str, Any]:
    """精确查重后创建，并读回关键字段避免把相似任务当作成功结果。"""
    found = client.verify_task_created(project_id, task['name'], exact=True)
    source = 'reused'
    if not found:
        source = 'created'
        try:
            client.create_task(project_id, task['name'], module=task['module'], assigned_to=task['assigned_to'],
                               task_type=task['task_type'], estimate=task['estimate'], begin=task['begin'],
                               end=task['end'], desc=task['desc'])
        except ZentaoWriteOutcomeUnknown:
            found = client.verify_task_created(project_id, task['name'], exact=True)
            if not found:
                raise
            source = 'recovered'
        else:
            found = client.verify_task_created(project_id, task['name'], exact=True)
    if not found:
        raise ZentaoError(f'创建后未找到精确名称任务: {task["name"]}')
    detail = client.get_task_detail(int(found['id']))
    expected = {'project': str(project_id), 'module': str(task['module']), 'assignedTo': task['assigned_to'],
                'type': task['task_type'], 'estimate': task['estimate'], 'left': task['estimate'],
                'estStarted': task['begin'], 'deadline': task['end']}
    actual = {key: detail_value(detail, key) for key in expected}
    mismatch = {key: [expected[key], actual[key]] for key in expected if str(actual[key]) != expected[key]}
    if mismatch:
        raise ZentaoError(f'任务 {found["id"]} 读回验证失败: {mismatch}')
    return {'id': found['id'], 'name': task['name'], 'source': source, **actual}


def run_batch(batch: Dict[str, Any], dry_run: bool) -> int:
    """批量入口：预检成功后才允许写入，整批只生成一张任务列表截图。"""
    client = ZentaoClient(ZentaoClient.detect_service_from_text(batch['user_text']))
    client.login_with_available_credentials()
    plan = preflight_batch(client, batch)
    if dry_run or plan.get('status') == 'needs_confirmation':
        print(json.dumps({'dry_run': dry_run, **plan}, ensure_ascii=False, indent=2))
        return 0 if dry_run else 1
    results = [create_and_verify(client, int(plan['project']['id']), task) for task in plan['tasks']]
    screenshot = client.screenshot_task_list()
    print(json.dumps({'dry_run': False, 'service': client.base_url, 'tasks': results,
                      'screenshot': screenshot}, ensure_ascii=False, indent=2))
    return 0


def legacy_batch(values: List[str], user_text: str) -> Dict[str, Any]:
    """保留既有单任务位置参数，内部统一转换为批量清单。"""
    if len(values) < 3:
        raise ZentaoError('参数不足：需要 项目ID 任务名称 模块ID')
    dates = default_dates()
    return {'project_id': int(values[0]), 'user_text': user_text or '', 'tasks': [{
        'name': values[1], 'module': int(values[2]), 'assigned_to': values[3] if len(values) > 3 else 'zhouwei',
        'task_type': values[4] if len(values) > 4 else 'devel', 'estimate': values[5] if len(values) > 5 else '10',
        'begin': values[6] if len(values) > 6 else dates['begin'], 'end': values[7] if len(values) > 7 else dates['end'],
        'desc': '',
    }]}


def confirm_test_task(batch: Dict[str, Any], force: bool) -> bool:
    """保留旧 CLI 的测试任务保护，避免非交互脚本误创建测试数据。"""
    keywords = ('测试', 'test', 'testv', 'v2', 'v3', 'v4', '最终', '完整', 'sample', 'demo', '示例', '临时', 'tmp')
    is_test_task = any(keyword in task['name'].lower() for task in batch['tasks'] for keyword in keywords)
    if not is_test_task or force:
        return True
    if not os.isatty(0):
        print('⚠️ 非交互模式，测试任务需添加 --force')
        return False
    return input("检测到测试任务，输入 'yes' 确认创建: ").strip().lower() in {'yes', 'y', '是', '确定'}


def main() -> int:
    args = build_parser().parse_args()
    if args.wizard:
        os.execl(sys.executable, sys.executable, os.path.join(os.path.dirname(__file__), 'zentao-wizard.py'))
    user_id = os.getenv('ZENTAO_CURRENT_USER', '')
    if user_id and not check_user_permission(user_id):
        print('错误: 您没有权限使用此功能')
        return 1
    try:
        source_path = args.approved_plan or args.batch_json
        batch = (
            load_batch(source_path, args.user_text, require_approved=bool(args.approved_plan))
            if source_path else legacy_batch(args.legacy, args.user_text)
        )
        if not args.dry_run and not confirm_test_task(batch, args.force):
            return 1
        return run_batch(batch, args.dry_run)
    except (VaultError, ZentaoError, ValueError) as error:
        print(f'✗ {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
