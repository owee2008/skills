#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道项目模块列表查询 - 使用公共库版本
"""

import sys
import os

# 添加脚本目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao_common import (
    ZentaoClient, VaultClient,
    ZentaoError, VaultError,
    format_module_list,
    check_user_permission
)


def print_usage():
    """打印使用说明"""
    print("""用法:
  zentao-list-modules.py <项目ID> [选项]
  zentao-list-modules.py <项目ID> --user-text "文本"

参数:
  项目ID       项目 ID（必填）

选项:
  --user-text  从用户文本中自动检测禅道服务
  -h, --help   显示此帮助

示例:
  # 基础用法
  ./zentao-list-modules.py 1681

  # 自动检测禅道服务
  ./zentao-list-modules.py 1681 --user-text "在科技部门禅道"
""")


def main():
    """主函数"""
    args = sys.argv[1:]
    
    # 检查帮助
    if not args or args[0] in ['-h', '--help']:
        print_usage()
        return 0
    
    # 获取项目ID
    project_id = args[0]
    if not project_id.isdigit():
        print("错误: 项目ID必须是数字")
        return 1
    
    # 检查权限
    user_id = os.getenv('ZENTAO_CURRENT_USER', '')
    if user_id and not check_user_permission(user_id):
        print("错误: 您没有权限使用此功能")
        return 1
    
    # 检测禅道服务
    zentao_url = None
    if len(args) > 1 and args[1] == '--user-text':
        if len(args) < 3:
            print("错误: --user-text 需要提供文本")
            return 1
        user_text = args[2]
        zentao_url = ZentaoClient.detect_service_from_text(user_text)
        print(f"自动选择的禅道服务: {zentao_url}")
    else:
        zentao_url = ZentaoClient._get_default_url()
    
    # 创建客户端
    client = ZentaoClient(zentao_url)
    
    try:
        # 登录
        print("正在登录禅道...")
        client.login_from_vault()
        print("✓ 登录成功\n")
        
        # 获取模块列表
        print(f"正在获取项目 {project_id} 的模块列表...")
        modules = client.get_modules(int(project_id))
        
        # 格式化输出
        print(format_module_list(modules))
        
        return 0
        
    except VaultError as e:
        print(f"✗ Vault 错误: {e}")
        return 1
    except ZentaoError as e:
        print(f"✗ 禅道错误: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
