#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道任务创建向导
提供交互式界面，引导用户完成任务创建
"""

import sys
import os

# 添加脚本目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao_common import (
    ZentaoClient, VaultClient, 
    ZentaoError, VaultError,
    format_project_list, format_module_list,
    check_user_permission
)

# 尝试加载yaml模块
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    print("警告: 未安装PyYAML模块，模块推荐功能将不可用")
    print("  安装命令: pip install pyyaml")

# 加载模块数据库
MODULES_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'modules.yaml')

def load_modules_db():
    """加载模块数据库"""
    if not HAS_YAML:
        return {'projects': {}}
    try:
        with open(MODULES_DB_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        return {'projects': {}}

def recommend_modules(project_id, task_name, modules_db):
    """
    根据任务名称推荐模块
    
    重要规则：一般任务只会创建在最底层模块中（二级及以下模块）
    
    Args:
        project_id: 项目ID
        task_name: 任务名称
        modules_db: 模块数据库
        
    Returns:
        推荐模块列表 [(module_id, module_name, reason)]
    """
    project_id_str = str(project_id)
    recommendations = []
    
    if project_id_str not in modules_db.get('projects', {}):
        return recommendations
    
    project_data = modules_db['projects'][project_id_str]
    modules = project_data.get('modules', {})
    keywords = project_data.get('keywords', {})
    
    task_name_lower = task_name.lower()
    
    # 根据关键词匹配
    matched_modules = set()
    for keyword, module_ids in keywords.items():
        if keyword in task_name_lower:
            for module_id in module_ids:
                module_id_str = str(module_id)
                if module_id_str not in matched_modules and module_id_str in modules:
                    module_name = modules[module_id_str]
                    matched_modules.add(module_id_str)
                    recommendations.append((module_id, module_name, f"匹配关键词: {keyword}"))
    
    # 如果没有匹配到，推荐前5个二级模块（最底层）
    if not recommendations:
        count = 0
        for module_id, module_name in modules.items():
            # 只推荐二级及以下模块（路径中包含两个或更多斜杠）
            if module_name.count('/') >= 2:  # /A/B 形式
                recommendations.append((int(module_id), module_name, "推荐二级模块"))
                count += 1
                if count >= 5:
                    break
    
    return recommendations


class Colors:
    """终端颜色"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_header(text):
    """打印标题"""
    print(f"\n{Colors.HEADER}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(60)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{'='*60}{Colors.ENDC}\n")


def print_success(text):
    """打印成功信息"""
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")


def print_error(text):
    """打印错误信息"""
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")


def print_info(text):
    """打印信息"""
    print(f"{Colors.OKBLUE}ℹ {text}{Colors.ENDC}")


def print_warning(text):
    """打印警告"""
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")


def input_required(prompt):
    """获取必填输入"""
    while True:
        value = input(f"{prompt} ").strip()
        if value:
            return value
        print_warning("此项为必填项，请输入内容")


def input_optional(prompt, default=None):
    """获取可选输入"""
    if default:
        value = input(f"{prompt} [{default}]: ").strip()
        return value if value else default
    else:
        value = input(f"{prompt}: ").strip()
        return value if value else None


def select_from_list(items, title, display_key='name', id_key='id'):
    """从列表中选择一项"""
    print(f"\n{title}:")
    print("-" * 50)
    
    for i, item in enumerate(items, 1):
        name = item.get(display_key, '未知')
        item_id = item.get(id_key, '')
        print(f"  {i}. {name} (ID: {item_id})")
    
    print("-" * 50)
    
    while True:
        choice = input("请选择编号 (输入数字): ").strip()
        
        if not choice.isdigit():
            print_warning("请输入数字")
            continue
        
        index = int(choice) - 1
        
        if index < 0 or index >= len(items):
            print_warning(f"请输入 1-{len(items)} 之间的数字")
            continue
        
        return items[index]


def confirm(prompt):
    """确认操作"""
    while True:
        response = input(f"{prompt} [y/n]: ").strip().lower()
        if response in ['y', 'yes', '是', '确定']:
            return True
        elif response in ['n', 'no', '否', '取消']:
            return False
        print_warning("请输入 y 或 n")


def select_zentao_service():
    """选择禅道服务"""
    print("\n请选择禅道服务:")
    print("-" * 50)
    print("  1. 田一部门 (默认)")
    print("  2. 科技部门")
    print("-" * 50)
    
    choice = input("请选择 [1]: ").strip()
    
    if choice == '2':
        url = os.getenv('ZENTAO_URL_KEJI', 'https://typm.tygps.com')
        print_info(f"已选择: 科技部门 ({url})")
    else:
        url = os.getenv('ZENTAO_URL_TIANYI', 'https://tycd.tygps.com')
        print_info(f"已选择: 田一部门 ({url})")
    
    return url


def select_project(client):
    """选择项目"""
    print_header("步骤 1/4: 选择项目")
    
    print("正在获取项目列表...")
    try:
        projects = client.get_projects()
        
        if not projects:
            print_error("没有找到可访问的项目")
            return None
        
        print_success(f"找到 {len(projects)} 个项目")
        
        # 如果项目太多，只显示前20个
        if len(projects) > 20:
            print_warning(f"项目较多，只显示前 20 个")
            projects = projects[:20]
        
        return select_from_list(projects, "请选择项目")
        
    except ZentaoError as e:
        print_error(f"获取项目列表失败: {e}")
        return None


def select_module(client, project_id):
    """选择模块"""
    print_header("步骤 2/4: 选择模块")
    
    print("正在获取模块列表...")
    try:
        modules = client.get_modules(project_id)
        
        if not modules:
            print_warning("该项目没有配置模块")
            if confirm("是否继续创建任务（无模块）?"):
                return {'id': 0, 'name': '无模块'}
            return None
        
        print_success(f"找到 {len(modules)} 个模块")
        
        return select_from_list(modules, "请选择模块")
        
    except ZentaoError as e:
        print_error(f"获取模块列表失败: {e}")
        if confirm("是否继续创建任务（无模块）?"):
            return {'id': 0, 'name': '无模块'}
        return None


def input_task_info(project_id=None):
    """输入任务信息"""
    print_header("步骤 3/4: 输入任务信息")
    
    # 任务名称
    name = input_required("📋 任务名称:")
    
    # 智能推荐模块
    selected_module = None
    if project_id and HAS_YAML:
        modules_db = load_modules_db()
        recommendations = recommend_modules(project_id, name, modules_db)
        
        if recommendations:
            print_header("🤖 智能模块推荐")
            print("根据任务名称，推荐以下模块:\n")
            
            for i, (module_id, module_name, reason) in enumerate(recommendations[:5], 1):
                print(f"  {i}. {module_name}")
                print(f"     原因: {reason}")
                print(f"     ID: {module_id}")
                print()
            
            print("选项:")
            print("  1-5: 选择推荐的模块")
            print("  m: 手动输入模块ID")
            print("  n: 不使用模块")
            
            choice = input("\n请选择 [1]: ").strip().lower()
            
            if choice in ['1', '2', '3', '4', '5']:
                idx = int(choice) - 1
                if idx < len(recommendations):
                    module_id, module_name, _ = recommendations[idx]
                    selected_module = {'id': module_id, 'name': module_name}
                    print_success(f"已选择模块: {module_name}")
            elif choice == 'm':
                # 手动输入模块ID
                module_id = input_required("请输入模块ID:")
                selected_module = {'id': int(module_id), 'name': f'模块{module_id}'}
            elif choice == 'n':
                selected_module = {'id': 0, 'name': '无模块'}
            else:
                # 默认选择第一个
                if recommendations:
                    module_id, module_name, _ = recommendations[0]
                    selected_module = {'id': module_id, 'name': module_name}
                    print_success(f"已选择模块: {module_name}")
    
    # 指派人
    assigned_to = input_optional("👤 指派人（用户名）", 'zhouwei')
    
    # 任务类型
    print("\n任务类型:")
    print("  1. 开发 (devel)")
    print("  2. 设计 (design)")
    print("  3. 测试 (test)")
    print("  4. 研究 (study)")
    print("  5. 讨论 (discuss)")
    print("  6. 界面 (ui)")
    print("  7. 其他 (affair)")
    
    type_choice = input("请选择 [1]: ").strip()
    task_types = {
        '1': 'devel', '2': 'design', '3': 'test', '4': 'study',
        '5': 'discuss', '6': 'ui', '7': 'affair'
    }
    task_type = task_types.get(type_choice, 'devel')
    
    # 预计工时
    estimate = input_optional("⏱ 预计工时（小时）", '10')
    
    # 日期
    from datetime import datetime, timedelta
    default_begin = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
    default_end = (datetime.now() + timedelta(days=10)).strftime('%Y-%m-%d')
    
    begin = input_optional("📅 开始日期", default_begin)
    end = input_optional("📅 结束日期", default_end)
    
    # 优先级
    print("\n优先级:")
    print("  1. 紧急")
    print("  2. 高")
    print("  3. 中 (默认)")
    print("  4. 低")
    
    pri_choice = input("请选择 [3]: ").strip()
    priorities = {'1': '1', '2': '2', '3': '3', '4': '4'}
    pri = priorities.get(pri_choice, '3')
    
    task_info = {
        'name': name,
        'assigned_to': assigned_to,
        'task_type': task_type,
        'estimate': estimate,
        'begin': begin,
        'end': end,
        'pri': pri,
        'module': selected_module  # 添加选中的模块
    }
    
    # ⚠️ 检查是否为测试任务
    test_keywords = ['测试', 'test', 'testv', 'v2', 'v3', 'v4', '最终', '完整', 'sample', 'demo', '示例', '临时', 'tmp']
    is_test_task = any(keyword in name.lower() for keyword in test_keywords)
    
    if is_test_task:
        print(f"\n⚠️  检测到可能的测试任务: {name}")
        print("任务名称包含以下关键词之一: 测试、test、v2、v3、最终、完整、sample、demo、示例、临时")
        print()
        if not confirm("确认创建此测试任务吗?"):
            return None
    
    return task_info


def confirm_task_info(project, module, task_info):
    """确认任务信息"""
    print_header("步骤 4/4: 确认信息")
    
    # 如果 task_info 为 None（用户取消了测试任务）
    if task_info is None:
        print("✗ 任务创建已取消")
        return False
    
    # 获取模块信息
    if module is None:
        module = task_info.get('module', {'id': 0, 'name': '无模块'})
    
    print("请确认以下信息:")
    print("-" * 50)
    print(f"  项目:    {project.get('name')} (ID: {project.get('id')})")
    print(f"  模块:    {module.get('name')} (ID: {module.get('id')})")
    print(f"  任务名:  {task_info['name']}")
    print(f"  指派人:  {task_info['assigned_to']}")
    print(f"  类型:    {task_info['task_type']}")
    if task_info['estimate']:
        print(f"  最初预计: {task_info['estimate']} 小时")
        print(f"  预计剩余: {task_info['estimate']} 小时")
    print(f"  预计开始日期: {task_info['begin']}")
    print(f"  截止日期:   {task_info['end']}")
    print(f"  优先级:  {task_info['pri']}")
    print("-" * 50)
    
    return confirm("确认创建任务?")


def main():
    """主流程"""
    print_header("🎯 禅道任务创建向导")
    
    # 检查权限
    user_id = os.getenv('ZENTAO_CURRENT_USER', '')
    if user_id and not check_user_permission(user_id):
        print_error("您没有权限使用此功能")
        print_info("请联系管理员添加权限")
        return 1
    
    # 选择禅道服务
    zentao_url = select_zentao_service()
    
    # 登录
    print("\n正在登录禅道...")
    try:
        client = ZentaoClient(zentao_url)
        client.login_from_vault()
        print_success("登录成功")
    except VaultError as e:
        print_error(f"Vault 错误: {e}")
        return 1
    except ZentaoError as e:
        print_error(f"登录失败: {e}")
        return 1
    
    # 选择项目
    project = select_project(client)
    if not project:
        return 1
    
    print_success(f"已选择项目: {project.get('name')}")
    
    # 输入任务信息（包含智能模块推荐）
    task_info = input_task_info(project_id=int(project.get('id')))
    
    # 检查是否取消
    if task_info is None:
        print_warning("已取消创建")
        return 0
    
    # 获取选中的模块
    module = task_info.get('module', {'id': 0, 'name': '无模块'})
    
    # 确认信息
    if not confirm_task_info(project, module, task_info):
        print_warning("已取消创建")
        return 0
    
    # 创建任务
    print("\n正在创建任务...")
    try:
        result = client.create_task(
            project_id=int(project.get('id')),
            name=task_info['name'],
            module=module.get('id'),
            assigned_to=task_info['assigned_to'],
            task_type=task_info['task_type'],
            estimate=task_info['estimate'],
            begin=task_info['begin'],
            end=task_info['end'],
            pri=task_info['pri']
        )
        
        if result.get('success'):
            print_header("✅ 任务创建成功")
            
            if 'id' in result:
                print_info(f"任务 ID: {result['id']}")
            
            # 验证任务
            print("\n正在验证任务...")
            verified = client.verify_task_created(
                int(project.get('id')),
                task_info['name']
            )
            
            if verified:
                print_success("验证通过！任务已成功创建")
                print(f"\n  任务名称: {verified.get('name')}")
                print(f"  任务 ID:  {verified.get('id')}")
            else:
                print_warning("无法验证任务，但创建请求已提交")
            
            return 0
        else:
            print_error(f"创建失败: {result.get('message', '未知错误')}")
            return 1
            
    except ZentaoError as e:
        print_error(f"创建任务失败: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
