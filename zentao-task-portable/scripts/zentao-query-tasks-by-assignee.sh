#!/bin/bash
# zentao-query-tasks-by-assignee.sh - 查询指派给特定用户的禅道任务
# 用法: ./zentao-query-tasks-by-assignee.sh <指派人用户名> [禅道URL]

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ASSIGNED_TO="$1"
ZENTAO_URL="${2:-${ZENTAO_URL:-${ZENTAO_URL_DEFAULT:-https://tycd.tygps.com}}}"

if [[ -z "$ASSIGNED_TO" ]]; then
    echo "用法: $0 <指派人用户名> [禅道URL]"
    echo "示例: $0 chenye"
    echo "      $0 chenye https://typm.tygps.com"
    exit 1
fi

# 浏览器配置目录由调用方指定；绝不删除固定路径的锁文件。
: "${ZENTAO_BROWSER_PROFILE_DIR:=}"
if [[ -n "$ZENTAO_BROWSER_PROFILE_DIR" ]]; then
    rm -f "$ZENTAO_BROWSER_PROFILE_DIR/SingletonLock" 2>/dev/null || true
fi

echo ""
echo "=========================================="
echo "  查询指派给 '$ASSIGNED_TO' 的任务"
echo "  禅道服务: $ZENTAO_URL"
echo "=========================================="
echo ""

# 只能从 Vault 获取凭据，禁止读取 ZENTAO_USERNAME/ZENTAO_PASSWORD 明文环境变量
USERNAME=""
PASSWORD=""
if command -v vault &> /dev/null; then
    if [[ -n "$VAULT_ADDR" && -n "$VAULT_TOKEN" ]]; then
        echo "正在从 Vault 读取禅道凭据..."
        VAULT_DATA=$(vault kv get -format=json secret/zentao/zhouwei 2>/dev/null || echo "{}")
        USERNAME=$(echo "$VAULT_DATA" | jq -r '.data.data.username // empty')
        PASSWORD=$(echo "$VAULT_DATA" | jq -r '.data.data.password // empty')
    fi
fi

if [[ -z "$USERNAME" || -z "$PASSWORD" ]]; then
    echo "错误: 无法获取禅道凭据"
    echo "请先恢复/解封 Vault 并配置 VAULT_ADDR 与 VAULT_TOKEN；禁止使用明文环境变量兜底"
    exit 1
fi

echo "正在登录禅道..."

# 登录
agent-browser --session zentao_query open "${ZENTAO_URL}/biz/user-login.html"
sleep 1

# 获取快照，找到输入框的 ref
WORKSPACE_DIR="${ZENTAO_WORKSPACE_DIR:-${HERMES_WORKSPACE:-$PWD}}"
mkdir -p "$WORKSPACE_DIR/zentao-artifacts"
SNAPSHOT_FILE="$WORKSPACE_DIR/zentao-artifacts/login_snapshot.txt"
agent-browser --session zentao_query snapshot -i > "$SNAPSHOT_FILE" 2>/dev/null || true

# 提取用户名输入框和密码输入框的 ref
USER_REF=$(grep -E "textbox.*ref" "$SNAPSHOT_FILE" | head -n 1 | grep -oE "ref=e[0-9]+" | head -n 1)
PASS_REF=$(grep -E "textbox.*ref" "$SNAPSHOT_FILE" | tail -n 1 | grep -oE "ref=e[0-9]+" | head -n 1)
LOGIN_REF=$(grep -E "button.*Login" "$SNAPSHOT_FILE" | grep -oE "ref=e[0-9]+" | head -n 1)

# 去掉 "ref=" 前缀
USER_REF="${USER_REF#ref=}"
PASS_REF="${PASS_REF#ref=}"
LOGIN_REF="${LOGIN_REF#ref=}"

echo "登录中..."

# 填写用户名和密码
if [[ -n "$USER_REF" ]]; then
    agent-browser --session zentao_query type "@${USER_REF}" "$USERNAME"
fi

if [[ -n "$PASS_REF" ]]; then
    agent-browser --session zentao_query type "@${PASS_REF}" "$PASSWORD
