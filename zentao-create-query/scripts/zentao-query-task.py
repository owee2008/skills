#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read one ZenTao task's editable live fields without changing it."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zentao_common import ZentaoClient, ZentaoError, VaultError


def main():
    parser = argparse.ArgumentParser(description='Query a ZenTao task by ID')
    parser.add_argument('task_id', type=int, help='ZenTao task ID')
    parser.add_argument('--user-text', default='', help='Service selector: tycd/田一 or typm/科技')
    args = parser.parse_args()

    text = args.user_text.lower()
    has_tycd = 'tycd' in text or '田一' in text
    has_typm = 'typm' in text or '科技' in text or '天远' in text
    if has_tycd and has_typm:
        print('错误: 禅道服务歧义；请只指定 tycd/田一 或 typm/科技/天远。', file=sys.stderr)
        return 2

    url = ZentaoClient.detect_service_from_text(args.user_text) if args.user_text else ZentaoClient._get_default_url()
    client = ZentaoClient(url)
    try:
        client.login_with_available_credentials()
        detail = client.get_task_detail(args.task_id)
        detail['service_url'] = url
        print(json.dumps(detail, ensure_ascii=False, indent=2, default=str))
        return 0
    except (VaultError, ZentaoError) as exc:
        print(f'错误: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
