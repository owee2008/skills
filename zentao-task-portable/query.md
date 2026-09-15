# 查询与截图

用于处理“查某人的任务”“确认任务状态”“截取任务页面”等请求。

## 按负责人查询任务

```bash
./scripts/zentao-query-tasks-by-assignee.sh <负责人账号>
```

输出应整理为易读列表，优先展示：

- 任务 ID
- 标题
- 状态
- 项目或模块
- 截止日期

## 任务截图

```bash
./scripts/zentao-screenshot-task.py <任务ID>
```

截图用于创建、修改、关闭后的可视化确认。若脚本保存图片，最终回复中说明图片路径；如果当前消息渠道支持发送图片，按渠道能力发送。

## 排查

- 登录失败：检查 `VAULT_TOKEN`、Vault sealed 状态、`secret/zentao/zhouwei` 凭据。
- 无权限：确认当前 Vault 账号是否能访问目标项目或任务。
- 任务不存在：确认使用的是田一还是科技部门禅道。
- 页面字段变化：参考 `references.md`，必要时重新检查禅道 HTML 表单字段。
