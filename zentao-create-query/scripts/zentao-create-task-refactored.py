#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道任务创建 - 使用公共库版本
基于 zentao_common.py 的简化实现

支持单条创建与批量创建（--batch，只登录一次）。
创建成功后一定回显任务 ID；未安装 Playwright 时静默跳过截图。
"""

import sys
import os
import json
import subprocess

# 添加脚本目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao_common import (
    ZentaoClient, VaultClient,
    ZentaoError, VaultError,
    playwright_available,
    check_user_permission
)


def print_usage():
    """打印使用说明"""
    print("""用法:
  单条: zentao-create-task-refactored.py [选项] <项目ID> <任务名称> <模块ID> [指派人] [类型] [工时] [开始] [截止]
  批量: zentao-create-task-refactored.py [选项] --batch <tasks.json>

参数:
  项目ID       项目 ID（必填）
  任务名称     任务名称（必填）
  模块ID       模块 ID（必填，0表示无模块）
  指派人       默认 zhouwei
  类型         默认 devel
  工时         默认 10
  开始/截止    YYYY-MM-DD，默认 T-5 / T+10

选项:
  --user-text  从用户文本中自动检测禅道服务
  --batch      批量模式，参数为 JSON 文件；数组元素字段：
               project / name / module / assigned_to / type / estimate / begin / end
  --force      跳过测试任务确认直接创建
  -h, --help   显示此帮助

环境变量:
  VAULT_ADDR          Vault 地址 (默认: http://127.0.0.1:8200)
  VAULT_TOKEN         Vault 令牌
  ZENTAO_URL_KEJI     科技/天远部门禅道地址
  ZENTAO_URL_TIANYI   田一部门禅道地址
  ZENTAO_URL_DEFAULT  默认禅道地址

示例:
  ./zentao-create-task-refactored.py 428 "任务名" 2939 zhoubinglong devel 14 2026-09-07 2026-09-13
  ./zentao-create-task-refactored.py --user-text "天远" 428 "任务名" 2939 zhoubinglong devel 14
  ./zentao-create-task-refactored.py --user-text "天远" --batch /tmp/tasks.json
""")


def spec_from_args(args):
    """把位置参数解析成一条任务规格"""
    if len(args) < 3:
        raise ValueError("参数不足")
    return {
        'project': int(args[0]),
        'name': args[1],
        'module': int(args[2]) if args[2] != '0' else 0,
        'assigned_to': args[3] if len(args) > 3 else 'zhouwei',
        'type': args[4] if len(args) > 4 else 'devel',
        'estimate': args[5] if len(args) > 5 and args[5] != '' else '10',
        'begin': args[6] if len(args) > 6 else '',
        'end': args[7] if len(args) > 7 else '',
    }


def specs_from_batch(path):
    """从 JSON 文件读取任务数组"""
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get('tasks', [])
    specs = []
    for i, item in enumerate(raw, 1):
        try:
            specs.append({
                'project': int(item.get('project', item.get('project_id'))),
                'name': item['name'],
                'module': int(item.get('module', 0) or 0),
                'assigned_to': item.get('assigned_to', 'zhouwei'),
                'type': item.get('type', 'devel'),
                'estimate': str(item.get('estimate', '10')),
                'begin': item.get('begin', ''),
                'end': item.get('end', ''),
            })
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"第 {i} 条任务字段不合法: {e}")
    return specs


TEST_KEYWORDS = ['测试', 'test', 'testv', 'v2', 'v3', 'v4', '最终', '完整', 'sample', 'demo', '示例', '临时', 'tmp']


def is_test_task(name):
    low = name.lower()
    return any(k in low for k in TEST_KEYWORDS)


def confirm_test_task(name):
    """命中测试关键词时确认；非交互环境直接取消"""
    print(f"⚠️  检测到可能的测试任务: {name}")
    print()
    if not os.isatty(0):
        print("⚠️  非交互模式，跳过测试任务。如需强制创建请添加 --force")
        return False
    try:
        user_input = input("确认创建此任务吗？输入 'yes' 或 'y' 继续，其他任何内容取消: ").strip()
    except EOFError:
        print("⚠️  无法读取输入，已取消。如需强制创建请添加 --force")
        return False
    if user_input.lower() not in ['yes', 'y', '是', '确定']:
        print("✗ 已取消创建")
        return False
    print()
    return True


def create_one(client, spec, force=False):
    """创建一条任务，返回 (ok, task_id)"""
    name = spec['name']
    begin_display = spec['begin'] or 'T-5'
    end_display = spec['end'] or 'T+10'

    if is_test_task(name) and not force and not confirm_test_task(name):
        return False, None

    print(f"\n正在创建任务: {name}")
    print(f"  最初预计工时: {spec['estimate']}小时")
    print(f"  预计剩余工时: {spec['estimate']}小时")
    print(f"  预计开始日期: {begin_display}")
    print(f"  截止日期: {end_display}")

    result = client.create_task(
        project_id=spec['project'],
        name=name,
        module=spec['module'],
        assigned_to=spec['assigned_to'],
        task_type=spec['type'],
        estimate=spec['estimate'],
        begin=spec['begin'],
        end=spec['end'],
    )

    if not result.get('success'):
        print(f"✗ 创建失败: {result.get('message', '未知错误')}")
        return False, None

    print("✓ 任务创建成功")
    print(f"  预计开始日期: {begin_display}")
    print(f"  截止日期: {end_display}")

    task_id = result.get('id')

    # 验证（同时用于补取 ID：部分禅道版本 locate 里不带 task-view）
    verified = client.verify_task_created(spec['project'], name)
    if verified:
        task_id = task_id or verified.get('id')
        print("✓ 验证通过")
    else:
        print("⚠ 未能在项目任务列表中精确匹配到该任务，请人工核对")

    if task_id:
        print(f"  任务 ID: {task_id}")
        print(f"  任务链接: {client.base_url}/biz/task-view-{task_id}.html")

    if playwright_available():
        print("\n正在生成任务截图...")
        shot = client.screenshot_task_list()
        if shot:
            print(f"📸 SCREENSHOT_PATH={shot}")
            print(f"📸 TASK_NAME={name}")
            print(f"📸 TASK_ID={task_id or 'unknown'}")

    return True, task_id


def main():
    """主函数"""
    args = sys.argv[1:]

    # 检查帮助
    if not args or args[0] in ['-h', '--help']:
        print_usage()
        return 0

    # 检查权限
    user_id = os.getenv('ZENTAO_CURRENT_USER', '')
    if user_id and not check_user_permission(user_id):
        print("错误: 您没有权限使用此功能")
        return 1

    # 启动向导模式
    if args[0] == '--wizard':
        wizard_path = os.path.join(os.path.dirname(__file__), 'zentao-wizard.py')
        os.execl(sys.executable, sys.executable, wizard_path)

    # 解析选项
    zentao_url = None
    force = False
    batch_path = None
    new_args = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == '--force':
            force = True
        elif a == '--batch':
            if i + 1 >= len(args):
                print("错误: --batch 需要提供 JSON 文件路径")
                return 1
            batch_path = args[i + 1]
            i += 2
            continue
        elif a == '--user-text':
            if i + 1 >= len(args):
                print("错误: --user-text 需要提供文本")
                return 1
            zentao_url = ZentaoClient.detect_service_from_text(args[i + 1])
            i += 2
            continue
        else:
            new_args.append(a)
        i += 1

    if zentao_url:
        print(f"自动选择的禅道服务: {zentao_url}")

    # 组装任务列表
    try:
        if batch_path:
            specs = specs_from_batch(batch_path)
        else:
            specs = [spec_from_args(new_args)]
    except ValueError as e:
        print(f"错误: {e}")
        print_usage()
        return 1

    client = ZentaoClient(zentao_url)

    try:
        print("正在登录禅道...")
        client.login_with_available_credentials()
        print("✓ 登录成功")
    except VaultError as e:
        print(f"✗ 凭据错误: {e}")
        return 1
    except ZentaoError as e:
        print(f"✗ 禅道错误: {e}")
        return 1

    print(f"\n共 {len(specs)} 条任务待创建")

    ok_ids, failed = [], []
    for spec in specs:
        try:
            ok, task_id = create_one(client, spec, force)
        except ZentaoError as e:
            print(f"✗ 创建异常（{spec['name']}）: {e}")
            ok, task_id = False, None
        if ok:
            ok_ids.append((spec['name'], task_id))
        else:
            failed.append(spec['name'])

    print("\n================ 汇总 ================")
    for name, task_id in ok_ids:
        print(f"  ✓ {task_id}\t{name}")
    for name in failed:
        print(f"  ✗ -\t{name}（未创建）")
    print(f"成功 {len(ok_ids)} / {len(specs)}")

    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
