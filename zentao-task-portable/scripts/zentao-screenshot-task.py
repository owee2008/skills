#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道任务截图 - 改进版
确保在截图前已登录
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zentao_common import ZentaoClient

def screenshot_task_with_login(task_id, task_name=None, project_id=None, user_text=None):
    """
    截图我的任务页面（确保已登录）。

    Args:
        task_id: 任务ID
        task_name: 任务名称（用于文件名）
        project_id: 项目ID（兼容参数；当前截图方法不依赖）
        user_text: 禅道服务提示文本，支持 typm/科技/天远 或 tycd/田一

    Returns:
        截图文件路径
    """
    zentao_url = ZentaoClient.detect_service_from_text(user_text or '')
    client = ZentaoClient(zentao_url)

    print(f"正在登录... ({client.base_url})")
    client.login_from_vault()
    print("✓ 登录成功")

    screenshot_path = client.screenshot_task(task_id, task_name or '', project_id or 0)

    if screenshot_path:
        print(f"✓ 截图已保存: {screenshot_path}")
        return screenshot_path
    else:
        print("✗ 截图失败")
        return None

if __name__ == '__main__':
    if len(sys.argv) >= 2:
        task_id = int(sys.argv[1])
    else:
        task_id = 66118

    if len(sys.argv) >= 3:
        user_text = sys.argv[2]
    else:
        user_text = "tycd"

    if len(sys.argv) >= 4:
        project_id = int(sys.argv[3])
    else:
        project_id = None

    task_name = f"{user_text}_任务{task_id}"
    screenshot_task_with_login(task_id, task_name, project_id, user_text)
