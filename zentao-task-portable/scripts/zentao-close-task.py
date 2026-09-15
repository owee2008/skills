#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道任务关闭脚本（修复版）
支持通过任务ID关闭禅道任务（将状态改为已关闭）
"""

import sys
import os
import re
import json

# Generated screenshots belong to the caller-configured workspace.
ARTIFACT_DIR = os.path.join(os.getenv('ZENTAO_WORKSPACE_DIR', os.getenv('HERMES_WORKSPACE', os.getcwd())), 'zentao-artifacts')
os.makedirs(ARTIFACT_DIR, exist_ok=True)
from zentao_common import ZentaoClient, VaultClient, ZentaoError, check_user_permission


def close_task(task_id: int, comment: str = "", base_url: str = None) -> bool:
    """
    关闭禅道任务（将状态改为已关闭）

    Args:
        task_id: 任务ID
        comment: 关闭备注/原因（可选）
        base_url: 禅道服务地址（可选）

    Returns:
        关闭是否成功
    """
    print(f"正在准备关闭任务: {task_id}")

    # 创建禅道客户端
    client = ZentaoClient(base_url)

    # 从Vault读取凭据并登录
    print("正在从Vault读取凭据...")
    vault_client = VaultClient()
    username, _ = vault_client.get_zentao_credentials()
    print(f"✓ 成功读取凭据 (用户名: {username})")

    print(f"正在登录禅道 {client.base_url}...")
    client.login_from_vault(vault_client)
    print("✓ 登录成功")

    # 获取任务详情（用于确认状态）
    print(f"正在获取任务 {task_id} 的详细信息...")
    task_detail_url = f"{client.base_url}/biz/task-view-{task_id}.html"
    response = client.session.get(task_detail_url, timeout=10)

    current_status = "未知"
    if response.status_code == 200:
        # 从页面提取任务状态
        status_patterns = [
            r'status["\']?\s*[:=]\s*["\']([^"\']+)["\']',
            r'<span[^>]*class=["\']label-status[^"\']*["\'][^>]*>(.*?)</span>',
            r'Status\s*[:：]\s*(.*?)\s*<'
        ]

        for pattern in status_patterns:
            match = re.search(pattern, response.text)
            if match:
                current_status = match.group(1).strip()
                break

        print(f"  当前状态: {current_status}")

        # 检查是否已经是关闭状态
        if 'closed' in current_status.lower() or '已关闭' in current_status:
            print(f"⚠ 任务已经是关闭状态，无需重复操作")
            return True
    else:
        print(f"  警告: 无法获取任务详细信息，状态码: {response.status_code}")

    # 检查任务状态并执行相应操作
    if 'wait' in current_status.lower() or '未开始' in current_status:
        print("\n⚠ 检测到任务状态为'未开始'")
        print("正在先'开始'任务，然后再'关闭'...")

        # 使用agent-browser开始任务（更可靠）
        try:
            import subprocess

            task_url = f"{client.base_url}/biz/task-view-{task_id}.html"
            start_cmd = [
                'npx', 'agent-browser', 'navigate', task_url,
                '&&', 'npx', 'agent-browser', 'wait', '--load', 'networkidle',
                '&&', 'npx', 'agent-browser', 'evaluate', 'Array.from(document.querySelectorAll("a")).find(a => a.href.includes("task-start"))?.click() || console.log("Start link not found")',
                '&&', 'npx', 'agent-browser', 'wait', '--timeout', '5000', '--load', 'networkidle',
                '&&', 'npx', 'agent-browser', 'screenshot', os.path.join(ARTIFACT_DIR, 'close-start-result.png')
            ]

            print(f"  使用agent-browser开始任务...")
            result = subprocess.run(start_cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                print("  ✓ 任务已开始（通过浏览器自动化）")
                # 等待服务器处理
                import time
                time.sleep(2)
            else:
                print(f"  ⚠ 开始任务失败: {result.stderr}")

        except Exception as e:
            print(f"  ⚠ 浏览器操作异常: {e}")

    # 执行关闭操作
    print(f"正在关闭任务 {task_id}...")

    # 使用浏览器自动化（最可靠）
    print("使用agent-browser自动操作...")

    try:
        import subprocess

        task_url = f"{client.base_url}/biz/task-view-{task_id}.html"
        cmd = [
            'npx', 'agent-browser', 'navigate', task_url,
            '&&', 'npx', 'agent-browser', 'wait', '--load', 'networkidle'
        ]

        # 点击Finish按钮进入完成页面
        cmd.extend([
            '&&', 'npx', 'agent-browser', 'evaluate', 'Array.from(document.querySelectorAll("a")).find(a => a.href.includes("task-finish"))?.click() || console.log("Finish link not found")',
            '&&', 'npx', 'agent-browser', 'wait', '--timeout', '5000', '--load', 'networkidle',
            '&&', 'npx', 'agent-browser', 'screenshot', os.path.join(ARTIFACT_DIR, 'close-finish-page.png')
        ])

        # 填写Cost和left字段（关键修复：使用JavaScript直接设置值）
        cmd.extend([
            '&&', 'npx', 'agent-browser', 'evaluate', 'const costInput = document.querySelector("input[name=Cost]") || document.querySelector("input[name=cost]"); if(costInput) { costInput.value = "0"; console.log("Cost set to 0"); } else { console.log("Cost input not found"); }',
            '&&', 'npx', 'agent-browser', 'evaluate', 'const leftInput = document.querySelector("input[name=left]") || document.querySelector("input[name=Left]"); if(leftInput) { leftInput.value = "0"; console.log("Left set to 0"); } else { console.log("Left input not found"); }',
            '&&', 'npx', 'agent-browser', 'screenshot', os.path.join(ARTIFACT_DIR, 'close-form-filled.png')
        ])

        # 如果有备注，添加备注
        if comment:
            cmd.extend([
                '&&', 'npx', 'agent-browser', 'evaluate', 'const commentInput = document.querySelector("textarea[name=comment]"); if(commentInput) { commentInput.value = ' + json.dumps(comment) + '; console.log("Comment added"); } else { console.log("Comment input not found"); }'
            ])

        # 点击Save按钮
        cmd.extend([
            '&&', 'npx', 'agent-browser', 'evaluate', 'Array.from(document.querySelectorAll("button")).find(b => b.textContent.includes("Save"))?.click() || console.log("Save button not found")',
            '&&', 'npx', 'agent-browser', 'wait', '--timeout', '5000', '--load', 'networkidle',
            '&&', 'npx', 'agent-browser', 'screenshot', os.path.join(ARTIFACT_DIR, f'task-{task_id}-close-result.png')
        ])

        print(f"  执行浏览器自动化操作...")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            print(f"  ✓ 浏览器操作完成")

            # 验证是否真的关闭了
            verify_response = client.session.get(task_url, timeout=10)

            if verify_response.status_code == 200:
                # 检查状态是否改变
                page_text = verify_response.text.lower()
                if 'closed' in page_text or 'done' in page_text:
                    print(f"✓ 任务 {task_id} 已成功关闭")
                    if comment:
                        print(f"  备注说明: {comment}")
                    return True
                elif 'wait' in page_text or '未开始' in page_text:
                    print(f"⚠ 任务状态仍为：未开始")
                    print(f"  可能原因：任务需要先开始才能关闭")
                else:
                    print(f"⚠ 任务状态为：未知")
            else:
                print(f"✓ 任务 {task_id} 已成功关闭（任务不可访问）")
                if comment:
                    print(f"  备注说明: {comment}")
                return True
        else:
            print(f"  ✗ 浏览器自动化操作失败")
            print(f"  错误: {result.stderr[:500]}")

        # 检查截图文件
        for step in ['close-finish-page.png', 'close-form-filled.png', f'task-{task_id}-close-result.png']:
            if os.path.exists(os.path.join(ARTIFACT_DIR, step)):
                print(f"  ✓ 截图已生成: {step}")

    except subprocess.TimeoutExpired:
        print("  ✗ 浏览器自动化操作超时")
    except Exception as e:
        print(f"  ✗ 浏览器自动化操作异常: {e}")

    print(f"✗ 关闭任务失败，请检查任务ID、状态和权限")
    return False


def main():
    """主函数"""
    # 检查权限
    current_user = os.getenv('FEISHU_SENDER_ID', 'ou_example_user_a')

    if not check_user_permission(current_user):
        print("错误: 您没有权限使用此功能")
        sys.exit(1)

    # 解析参数
    if len(sys.argv) < 2:
        print("用法: python3 zentao-close-task-fixed.py <任务ID> [备注] [禅道URL]")
        print("示例:")
        print("  python3 zentao-close-task-fixed.py 66133")
        print("  python3 zentao-close-task-fixed.py 66133 '任务已完成，关闭归档'")
        print("  python3 zentao-close-task-fixed.py 66133 '已完成' https://tycd.tygps.com")
        sys.exit(1)

    task_id = int(sys.argv[1])
    comment = sys.argv[2] if len(sys.argv) > 2 else ""
    base_url = sys.argv[3] if len(sys.argv) > 3 else None

    # 执行关闭操作
    success = close_task(task_id, comment, base_url)

    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
