#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
禅道任务取消脚本 V2 - HTTP 表单模拟版
通过模拟 HTTP 请求实现任务取消，不依赖浏览器自动化

核心流程:
1. 登录禅道
2. GET /biz/task-cancel-{id}.html 获取取消表单
3. 提取 kuid 值
4. POST 提交取消（携带 uid=kuid + comment）
5. 验证任务状态变为 cancelled

用法:
    python3 zentao-cancel-task-v2.py <任务ID>
    python3 zentao-cancel-task-v2.py <任务ID> [禅道URL]
"""

import sys
import os
import re
import json
import time
from typing import Dict, Optional

# 导入公共库
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zentao_common import (
    ZentaoClient, VaultClient, ZentaoError, VaultError,
    check_user_permission
)


class TaskCancelError(Exception):
    """取消任务异常"""
    pass


class ZentaoCancelClient(ZentaoClient):
    """扩展 ZentaoClient，添加取消任务能力"""

    def get_task_detail(self, task_id: int) -> Optional[Dict]:
        """
        获取任务详情

        Args:
            task_id: 任务 ID

        Returns:
            任务信息字典，或 None
        """
        if not self._logged_in:
            raise ZentaoError("未登录")

        url = f"{self.base_url}/biz/task-view-{task_id}.html"
        resp = self.session.get(url, timeout=10)
        if resp.status_code != 200:
            return None

        html = resp.text
        info = {'id': task_id}

        # 提取任务名称（从标题）
        title_match = re.search(r'<title>TASK#\d+\s+([^/]+)', html)
        if title_match:
            info['name'] = title_match.group(1).strip()

        # 提取任务状态（从历史记录）
        status_match = re.search(r'cancelled by|已取消', html, re.IGNORECASE)
        if status_match:
            info['status'] = 'cancelled'
        else:
            # 尝试从状态标签提取
            status_patterns = [
                r'class=["\'][^"\']*label-status[^"\']*["\'][^>]*>([^<]+)<',
                r'状态.*?</td>.*?<td[^>]*>([^<]+)<',
            ]
            for pat in status_patterns:
                m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
                if m:
                    info['status'] = m.group(1).strip()
                    break

        return info

    def cancel_task(self, task_id: int, comment: str = "") -> Dict:
        """
        取消禅道任务

        Args:
            task_id: 任务 ID
            comment: 取消备注（可选）

        Returns:
            包含 success, message, task_status 的字典

        Raises:
            TaskCancelError: 取消失败时抛出
        """
        if not self._logged_in:
            raise TaskCancelError("未登录")

        # Step 1: 获取取消表单页面
        cancel_url = f"{self.base_url}/biz/task-cancel-{task_id}.html"
        params = {'onlybody': 'yes'}

        resp = self.session.get(cancel_url, params=params, timeout=15)

        if resp.status_code == 404:
            raise TaskCancelError(f"任务 {task_id} 不存在或已删除")
        elif resp.status_code != 200:
            raise TaskCancelError(f"无法访问取消页面，HTTP {resp.status_code}")

        html = resp.text

        # Step 2: 提取 kuid
        kuid = None
        kuid_patterns = [
            r"kuid\s*=\s*['\"]([^'\"]+)['\"]",
            r"['\"]kuid['\"]\s*[:=]\s*['\"]([^'\"]+)['\"]",
        ]
        for pat in kuid_patterns:
            m = re.search(pat, html)
            if m:
                kuid = m.group(1)
                break

        if not kuid:
            raise TaskCancelError("无法提取表单 kuid 值")

        # Step 3: 构建表单数据
        form_data = {
            'uid': kuid,
            'comment': comment or '',
        }

        # Step 4: POST 提交取消
        cancel_resp = self.session.post(
            cancel_url,
            data=form_data,
            headers={
                'Referer': f"{self.base_url}/biz/task-view-{task_id}.html",
                'X-Requested-With': 'XMLHttpRequest',
            },
            timeout=15
        )

        # Step 5: 解析响应
        result = self._parse_cancel_response(cancel_resp, task_id)

        if result['success']:
            # Step 6: 二次验证
            time.sleep(1)
            verified_status = self._verify_cancelled(task_id)
            if verified_status:
                result['task_status'] = verified_status
            else:
                result['message'] += " (验证失败，请手动确认)"

        return result

    def _parse_cancel_response(self, resp, task_id: int) -> Dict:
        """解析取消操作的响应"""
        result = {'success': False, 'message': '', 'task_status': None}

        # 禅道取消成功返回的是 JS 跳转脚本
        # 例如: <script>parent.location='/biz/task-view-66150.html';</script>
        html = resp.text.lower()

        # 检查是否有 parent.location 跳转
        if 'parent.location' in html or 'window.location' in html:
            result['success'] = True
            result['message'] = f"任务 {task_id} 取消请求已提交"
            return result

        # 尝试 JSON 响应
        try:
            json_data = resp.json()
            if json_data.get('result') == 'success':
                result['success'] = True
                result['message'] = json_data.get('message', f"任务 {task_id} 已成功取消")
            else:
                result['message'] = json_data.get('message', '未知错误')
            return result
        except:
            pass

        # 检查 alert 错误
        alert_m = re.search(r"alert\(['\"](.+?)['\"]\)", resp.text)
        if alert_m:
            result['message'] = f"服务器返回错误: {alert_m.group(1)}"
            return result

        result['message'] = f"无法解析取消响应 (HTTP {resp.status_code})"
        return result

    def _verify_cancelled(self, task_id: int) -> Optional[str]:
        """验证任务是否已取消"""
        try:
            url = f"{self.base_url}/biz/task-view-{task_id}.html"
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 404:
                return "已删除"

            html = resp.text
            # 检查是否有取消记录
            if re.search(r'cancelled by|已取消', html, re.IGNORECASE):
                return "已取消"

            # 检查是否还有取消按钮
            if 'task-cancel' not in html.lower():
                return "页面无取消按钮，可能已取消"

            return None
        except:
            return None


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python3 zentao-cancel-task-v2.py <任务ID> [禅道URL]")
        print("示例:")
        print("  python3 zentao-cancel-task-v2.py 66132")
        print("  python3 zentao-cancel-task-v2.py 66132 https://tycd.tygps.com")
        sys.exit(1)

    task_id = int(sys.argv[1])
    base_url = sys.argv[2] if len(sys.argv) > 2 else None
    comment = ""

    # 权限检查
    current_user = os.getenv('FEISHU_SENDER_ID', '')
    if current_user and not check_user_permission(current_user):
        print("错误: 您没有权限使用此功能")
        sys.exit(1)

    # 创建客户端
    client = ZentaoCancelClient(base_url)

    # 登录
    print(f"正在登录禅道 {client.base_url}...")
    try:
        vault = VaultClient()
        client.login_from_vault(vault)
        print("✓ 使用 Vault 凭据登录成功")
    except ZentaoError as e:
        print(f"✗ 登录失败: {e}")
        sys.exit(1)
    except VaultError as e:
        print(f"✗ Vault 错误: {e}")
        sys.exit(1)

    # 获取任务信息
    print(f"\n正在获取任务 {task_id} 信息...")
    try:
        detail = client.get_task_detail(task_id)
        if detail:
            print(f"  任务名称: {detail.get('name', '未知')}")
            print(f"  当前状态: {detail.get('status', '未知')}")
        else:
            print("  警告: 无法获取任务详情")
    except Exception as e:
        print(f"  警告: 获取任务详情失败: {e}")

    # 执行取消
    print(f"\n正在取消任务 {task_id}...")
    try:
        result = client.cancel_task(task_id, comment)
        if result['success']:
            print(f"✓ {result['message']}")
            if result.get('task_status'):
                print(f"  验证状态: {result['task_status']}")
            sys.exit(0)
        else:
            print(f"✗ {result['message']}")
            sys.exit(1)
    except TaskCancelError as e:
        print(f"✗ 取消失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ 异常: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
