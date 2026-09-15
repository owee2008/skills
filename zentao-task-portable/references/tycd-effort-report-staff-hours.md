# 田一禅道：按员工统计月度总工时与指定日志 ID 工时

## 场景

用户给出一批 `zt_effort.id` 日志 ID，要求按人统计这些日志的工时；随后可能要求对这些人查询某个月在禅道报表中的总工时。

## 指定日志 ID 按人汇总

1. 登录田一禅道：`https://tycd.tygps.com/biz`。
2. 用 SQL 接口查询 `zt_effort`，并关联用户与任务：

```sql
select e.id,e.date,e.account,u.realname,e.consumed,e.`left`,e.work,e.project,e.objectID,e.objectType,t.name as taskName
from zt_effort e
left join zt_user u on u.account=e.account
left join zt_task t on t.id=e.objectID and e.objectType='task'
where e.id in (<ids>)
order by field(e.id,<ids>)
```

3. 汇总口径默认按日志 ID 去重；如果用户的输入列表有重复 ID，要在回复里明确说明重复项，并可同时给出“按原始输入重复计入”的差异。
4. 按人汇总 SQL：

```sql
select coalesce(u.realname,e.account) as person, e.account,
       count(*) as logCount,
       cast(sum(e.consumed) as decimal(10,2)) as hours
from zt_effort e
left join zt_user u on u.account=e.account
where e.id in (<unique_ids>)
group by e.account,u.realname
order by person
```

## 禅道员工月度总工时报表

用户可能提供浏览器复制的 curl，例如：

```bash
curl 'https://tycd.tygps.com/biz/report-show-59-staff.html' \
  -X POST \
  --data 'sqlVars%5Bstart1%5D=2026-06-01&sqlVars%5Bend1%5D=2026-06-30'
```

不要直接复用用户贴出的 Cookie；优先用已有 Vault 凭据重新登录，然后 POST 表单参数：

```python
html = client.post('/report-show-59-staff.html', {
    'sqlVars[start1]': '2026-06-01',
    'sqlVars[end1]': '2026-06-30',
})
```

报表 HTML 中有：

```html
<table class='reportData ...'>
  <th>Name</th><th>工时累计</th>
  <tr><td>周维</td><td>170.00999999977648</td></tr>
</table>
```

解析 `table.reportData` 的两列：员工姓名、工时累计。根据前一步按日志 ID 汇总得到的人员名单筛选报表结果。

## 回复格式建议

- 先写明报表范围（例如 `2026-06-01 ~ 2026-06-30`）与“全部人员均查到 / 未查到名单”。
- 用表格列出：人员、6 月总工时。
- 禅道报表可能返回浮点尾差（如 `170.00999999977648`、`123.90000009536743`），展示时四舍五入到两位小数，并在必要时说明原始值。
- 如用户连续给多批日志 ID，合并统计时默认按日志 ID 去重；若存在重复 ID，明确提示。
