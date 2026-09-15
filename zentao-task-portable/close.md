# 取消与关闭任务

用于处理“取消任务”“关闭任务”“任务完成后关闭”等请求。

## 取消任务

推荐脚本：

```bash
./scripts/zentao-cancel-task-v2.py <任务ID>
```

适合未完成、不再执行、需求取消等场景。脚本通过 HTTP 表单模拟处理，依赖 Vault 登录。

## 关闭任务

```bash
./scripts/zentao-close-task.py <任务ID>
./scripts/zentao-close-task.py <任务ID> "关闭备注"
```

适合任务完成后关闭。备注应简短说明关闭原因或完成情况。

## 回复要求

最终说明：

- 操作类型：取消或关闭
- 任务 ID
- 是否成功
- 脚本返回的关键提示
- 未成功时的失败原因和下一步
