#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道项目列表查询 - 使用公共库版本
"""

import sys
import os

# 添加脚本目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao_common import (
    ZentaoClient, VaultClient,
    ZentaoError, VaultError,
    format_project_list,
    check_user_permission
)


def main():
    """主函数"""
    args = sys.argv[1:]
    
    # 检查帮助
    if args and args[0] in ['-h', '--help']:
        print("""用法:
  zentao-list-projects.py [选项]
  zentao-list-projects.py --user-text "文本"

选项:
  --user-text  从用户文本中自动检测禅道服务
  -h, --help   显示此帮助

示例:
  # 使用默认禅道服务
  ./zentao-list-projects.py

  # 自动检测禅道服务
  ./zentao-list-projects.py --user-text "在科技部门禅道"
""")
        return 0
    
    # 检查权限
    user_id = os.getenv('ZENTAO_CURRENT_USER', '')
    if user_id and not check_user_permission(user_id):
        print("错误: 您没有权限使用此功能")
        return 1
    
    # 检测禅道服务
    zentao_url = None
    if args and args[0] == '--user-text':
        if len(args) < 2:
            print("错误: --user-text 需要提供文本")
            return 1
        user_text = args[1]
        zentao_url = ZentaoClient.detect_service_from_text(user_text)
        print(f"自动选择的禅道服务: {zentao_url}")
    else:
        zentao_url = ZentaoClient._get_default_url()
    
    # 创建客户端
    client = ZentaoClient(zentao_url)
    
    try:
        # 登录
        print("正在登录禅道...")
        client.login_with_available_credentials()
        print("✓ 登录成功\n")
        
        # 获取项目列表
        print("正在获取项目列表...")
        projects = client.get_projects()
        
        # 格式化输出
        print(format_project_list(projects))
        
        return 0
        
    except VaultError as e:
        print(f"✗ 凭据错误: {e}")
        return 1
    except ZentaoError as e:
        print(f"✗ 禅道错误: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
