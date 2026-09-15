#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创建禅道任务；支持单条兼容参数和同项目批量清单。"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao_common import ZentaoClient, ZentaoError, VaultError, check_user_permission


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='创建禅道任务')
    parser.add_argument('legacy', nargs='*', metavar='参数', help='兼容：项目ID 任务名 模块ID [负责人 类型 工时 开始 截止]')
    parser.add_argument('--batch-json', help='批量清单 JSON 文件；包含 project_id、tasks 和可选 user_text')
    parser.add_argument('--dry-run', action='store_true', help='只登录和预检，不创建任务')
    parser.add_argument('--user-text', help='用于识别 tycd 或 typm 服务')
    parser.add_argument('--force', action='store_true', help='兼容旧参数；批量模式不需要交互确认')
    parser.add_argument('--wizard', action='store_true', help='启动原交互式向导')
    return parser


def default_dates() -> Dict[str, str]:
    """在实际执行时计算默认日期，避免确认后跨日仍沿用旧日期。"""
    today = date.today()
    return {'begin': str(today - timedelta(days=5)), 'end': str(today + timedelta(days=10))}


def load_batch(path: str, user_text: str = None) -> Dict[str, Any]:
    """读取并规范化最小批量清单，所有任务必须明确模块和负责人。"""
    try:
        with open(path, encoding='utf-8') as handle:
            batch = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ZentaoError(f'无法读取批量清单: {error}')
    if not isinstance(batch, dict) or not str(batch.get('project_id', '')).isdigit():
        raise ZentaoError('批量清单必须包含数字 project_id')
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
        try:
            task = {
                'name': str(source['name']).strip(), 'module': int(source['module']),
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
    return {'project_id': int(batch['project_id']), 'user_text': user_text or batch.get('user_text', ''), 'tasks': tasks}


def leaf_modules(modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """仅保留没有下级路径的模块，供预检输出给用户确认。"""
    names = [str(module.get('name', '')).rstrip('/') for module in modules]
    return [module for module in modules if not any(
        other.startswith(f"{str(module.get('name', '')).rstrip('/')}/") for other in names
    )]


def preflight_batch(client: ZentaoClient, batch: Dict[str, Any]) -> Dict[str, Any]:
    """一次登录内校验项目、模块和负责人；此函数绝不写入禅道。"""
    project_id = batch['project_id']
    project = client.get_project_info(project_id)
    if str(project.get('status', '')).lower() in {'closed', 'done'}:
        raise ZentaoError(f'项目 {project_id} 当前状态不可创建: {project.get("status")}')
    options = client.get_task_creation_options(project_id)
    module_ids = {int(module['id']) for module in options['modules']}
    assignees = {item['account'] for item in options['assignees']}
    for task in batch['tasks']:
        if task['module'] not in module_ids:
            raise ZentaoError(f'模块 {task["module"]} 不属于项目 {project_id}')
        if assignees and task['assigned_to'] not in assignees:
            raise ZentaoError(f'负责人 {task["assigned_to"]} 不在项目 {project_id} 的创建页下拉中')
    return {
        'service': client.base_url,
        'project': {key: project.get(key) for key in ('id', 'name', 'status')},
        'leaf_modules': leaf_modules(options['modules']), 'tasks': batch['tasks'],
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
        client.create_task(project_id, task['name'], module=task['module'], assigned_to=task['assigned_to'],
                           task_type=task['task_type'], estimate=task['estimate'], begin=task['begin'],
                           end=task['end'], desc=task['desc'])
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
    if dry_run:
        print(json.dumps({'dry_run': True, **plan}, ensure_ascii=False, indent=2))
        return 0
    results = [create_and_verify(client, batch['project_id'], task) for task in batch['tasks']]
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
        batch = load_batch(args.batch_json, args.user_text) if args.batch_json else legacy_batch(args.legacy, args.user_text)
        if not args.dry_run and not confirm_test_task(batch, args.force):
            return 1
        return run_batch(batch, args.dry_run)
    except (VaultError, ZentaoError, ValueError) as error:
        print(f'✗ {error}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
