#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道任务修改脚本

仅支持修改基础字段：
- 标题 name
- 模块 module
- 预计工时 estimate
- 剩余工时 left
- 截止日期 deadline

模块修改安全规则：
修改模块时必须获取并展示项目完整模块列表，且模块 ID 必须由用户显式提供
或在向导中明确选择，禁止按任务标题自动推断模块。
"""

import argparse
import os
import sys
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao_common import (  # noqa: E402
    ZentaoClient,
    ZentaoError,
    VaultError,
    check_user_permission,
    format_module_list,
)


EDITABLE_FIELDS = {
    'name': '标题',
    'module': '模块',
    'estimate': '预计工时',
    'left': '剩余工时',
    'estStarted': '开始日期',
    'deadline': '截止日期',
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='修改禅道任务基础信息',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  ./zentao-edit-task.py 66136 --name "新的任务标题"
  ./zentao-edit-task.py 66136 --estimate 8 --left 6 --deadline 2026-05-06 --yes
  ./zentao-edit-task.py 66136 --project-id 1681 --module 9646
  ./zentao-edit-task.py 66136 --wizard
  ./zentao-edit-task.py --user-text "在科技部门禅道" 66136 --name "新的任务标题"
"""
    )
    parser.add_argument('task_id', nargs='?', type=int, help='任务 ID')
    parser.add_argument('--user-text', help='从用户文本中自动检测禅道服务')
    parser.add_argument('--project-id', type=int, help='任务所属项目 ID；修改模块时用于获取完整模块列表')
    parser.add_argument('--name', help='新标题')
    parser.add_argument('--module', type=int, help='新模块 ID；必须显式指定，不会自动推荐/推断')
    parser.add_argument('--estimate', help='新预计工时')
    parser.add_argument('--left', help='新剩余工时')
    parser.add_argument('--start-date', help='新开始日期，格式 YYYY-MM-DD')
    parser.add_argument('--deadline', help='新截止日期，格式 YYYY-MM-DD')
    parser.add_argument('--wizard', action='store_true', help='启动交互式修改向导')
    parser.add_argument('--yes', action='store_true', help='跳过最终确认（模块仍必须显式指定并通过列表校验）')
    return parser


def print_header(text: str):
    print(f"\n{'=' * 60}")
    print(text.center(60))
    print(f"{'=' * 60}")


def confirm(prompt: str) -> bool:
    if not os.isatty(0):
        return False
    answer = input(f"{prompt} [y/n]: ").strip().lower()
    return answer in {'y', 'yes', '是', '确定'}


def input_optional(prompt: str, current: Any = '') -> Optional[str]:
    current_display = '' if current is None else str(current)
    value = input(f"{prompt} [{current_display}]: ").strip()
    return value if value else None


def normalize_changes(args: argparse.Namespace) -> Dict[str, Any]:
    changes = {}
    for field in EDITABLE_FIELDS:
        if field == 'estStarted':
            # estStarted is mapped from --start-date CLI arg
            if args.start_date is not None:
                changes['estStarted'] = args.start_date
            continue
        value = getattr(args, field)
        if value is not None:
            changes[field] = value
    return changes


def resolve_project_id(detail: Dict[str, Any], explicit_project_id: Optional[int]) -> Optional[int]:
    if explicit_project_id:
        return explicit_project_id

    raw_project = detail.get('project')
    if raw_project and str(raw_project).isdigit():
        return int(raw_project)

    return None


def validate_module_choice(client: ZentaoClient, project_id: int, module_id: int) -> Dict[str, Any]:
    print(f"\n正在获取项目 {project_id} 的完整模块列表...")
    modules = client.get_modules(project_id)
    print(format_module_list(modules))

    if module_id == 0:
        return {'id': 0, 'name': '无模块'}

    for module in modules:
        if int(module.get('id')) == int(module_id):
            print(f"\n✓ 已明确选择模块: {module.get('name')} (ID: {module_id})")
            return module

    raise ZentaoError(f"模块 ID {module_id} 不在项目 {project_id} 的模块列表中")


def select_module_interactively(client: ZentaoClient, project_id: int) -> int:
    print(f"\n正在获取项目 {project_id} 的完整模块列表...")
    modules = client.get_modules(project_id)
    print(format_module_list(modules))

    print("\n请选择模块：")
    print("  输入模块 ID，例如 9646")
    print("  输入 0 表示无模块")
    while True:
        raw = input("模块 ID: ").strip()
        if not raw.isdigit():
            print("请输入数字模块 ID")
            continue
        module_id = int(raw)
        validate_module_choice(client, project_id, module_id)
        return module_id


def print_task_detail(detail: Dict[str, Any]):
    print_header("当前任务信息")
    print(f"  任务 ID:   {detail.get('id')}")
    print(f"  标题:      {detail.get('name', '')}")
    print(f"  项目 ID:   {detail.get('project', '') or '未知'}")
    print(f"  模块 ID:   {detail.get('module', '')}")
    print(f"  预计工时:  {detail.get('estimate', '')}")
    print(f"  剩余工时:  {detail.get('left', '')}")
    print(f"  截止日期:  {detail.get('deadline', '')}")
    print(f"  开始日期:  {detail.get('estStarted', '')}")


def print_diff(detail: Dict[str, Any], changes: Dict[str, Any], selected_module: Optional[Dict[str, Any]] = None):
    print_header("修改确认")
    print(f"任务 ID: {detail.get('id')}\n")
    print(f"{'字段':<12} {'原值':<28} {'新值'}")
    print("-" * 70)
    for key, new_value in changes.items():
        label = EDITABLE_FIELDS[key]
        old_value = detail.get(key, '')
        if key == 'module' and selected_module:
            new_display = f"{selected_module.get('name', '')} (ID: {new_value})"
        else:
            new_display = str(new_value)
        print(f"{label:<12} {str(old_value):<28} {new_display}")
    print("-" * 70)


def collect_wizard_changes(client: ZentaoClient, detail: Dict[str, Any], project_id: Optional[int]) -> Dict[str, Any]:
    print_header("选择要修改的字段")
    changes: Dict[str, Any] = {}

    name = input_optional("新标题，回车跳过", detail.get('name', ''))
    if name is not None:
        changes['name'] = name

    if confirm("是否修改模块？"):
        if not project_id:
            raw_project = input("无法自动识别项目 ID，请输入项目 ID: ").strip()
            if not raw_project.isdigit():
                raise ZentaoError("项目 ID 必须是数字；无法修改模块")
            project_id = int(raw_project)
        changes['module'] = select_module_interactively(client, project_id)

    estimate = input_optional("新预计工时，回车跳过", detail.get('estimate', ''))
    if estimate is not None:
        changes['estimate'] = estimate

    left = input_optional("新剩余工时，回车跳过", detail.get('left', ''))
    if left is not None:
        changes['left'] = left

    deadline = input_optional("新截止日期 YYYY-MM-DD，回车跳过", detail.get('deadline', ''))
    if deadline is not None:
        changes['deadline'] = deadline

    return changes


def run(args: argparse.Namespace) -> int:
    if not args.task_id:
        print("错误: 缺少任务 ID")
        return 1

    user_id = os.getenv('ZENTAO_CURRENT_USER', '')
    if user_id and not check_user_permission(user_id):
        print("错误: 您没有权限使用此功能")
        return 1

    zentao_url = ZentaoClient.detect_service_from_text(args.user_text) if args.user_text else None
    if zentao_url:
        print(f"自动选择的禅道服务: {zentao_url}")

    client = ZentaoClient(zentao_url)

    try:
        print("正在登录禅道...")
        client.login_with_available_credentials()
        print("✓ 登录成功")

        detail = client.get_task_detail(args.task_id)
        print_task_detail(detail)

        project_id = resolve_project_id(detail, args.project_id)
        changes = collect_wizard_changes(client, detail, project_id) if args.wizard else normalize_changes(args)

        if not changes:
            print("\n没有指定任何修改字段，已退出")
            return 0

        selected_module = None
        if 'module' in changes:
            if project_id is None:
                raise ZentaoError("修改模块需要项目 ID：请使用 --project-id <项目ID> 或在向导中输入")
            selected_module = validate_module_choice(client, project_id, int(changes['module']))

        print_diff(detail, changes, selected_module)

        if not args.yes and not confirm("确认提交以上修改？"):
            print("已取消修改")
            return 0

        print("\n正在提交修改...")
        result = client.update_task(args.task_id, **changes)
        print(f"✓ 修改请求已提交: {result.get('message', '')}")

        print("\n正在验证修改结果...")
        verification = client.verify_task_updated(args.task_id, changes)
        if verification['success']:
            print("✓ 验证通过，任务信息已更新")
            return 0

        print("⚠ 修改请求已提交，但部分字段验证不一致：")
        for field, mismatch in verification['mismatches'].items():
            print(f"  - {EDITABLE_FIELDS.get(field, field)}: 期望 {mismatch['expected']}，实际 {mismatch['actual']}")
        return 1

    except VaultError as e:
        print(f"✗ 凭据错误: {e}")
        return 1
    except ZentaoError as e:
        print(f"✗ 禅道错误: {e}")
        return 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
