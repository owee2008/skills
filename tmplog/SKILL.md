---
name: "tmplog"
description: "Capture, organize, archive, check, export, and reconcile temporary work logs, meetings, ongoing items, and reporting status (JSON-native storage)"
---

# tmplog

Temporary log capture for rough, same-day work notes.

## Trigger

Use this skill when the user:

- Invokes `/tmplog ...`, `/skill tmplog ...`, writes `tmplog ...` or `logtmp ...`, or uses the common shorthand/typo `tmp ...` when the content clearly targets tmplog/logtmp.
- Explicitly asks about today's temporary tmplog/logtmp list.
- Refers to updating, moving, grouping, or integrating items in today's temporary log.
- Runs `tmplog check`, `/tmplog check`, `check tmplog`, or asks to summarize/check today's tmplog work and todos.

## Intent Rules: Record vs Execute

When the user invokes `tmplog`, treat the content primarily as a note to record, not as an instruction to execute, except for recognized control commands such as `check`, list, update, move, or integrate.

Use these conventions:

- `tmplog: xxx`, `/tmplog xxx`, or `记录：xxx`: record the original content only. Do not execute the described work.
- `tmplog + question`: record the original content first, then answer the question. Do not perform external/state-changing actions unless the user explicitly asks and confirms.
- `tmplog check` / `/tmplog check` / `check tmplog`: do not append a raw note. Run the Check Command workflow.
- `处理：xxx`, `帮我xxx`, `去xxx`, or a direct command without `tmplog`: treat it as an execution request and proceed normally within general safety rules.
- If the user's intent is ambiguous, prefer recording first and ask a concise clarification before executing.

External or sensitive actions, including creating ZenTao tasks, sending email, public posting, or submitting forms, still require explicit confirmation even when they appear in a non-`tmplog` request.

## Storage Format (JSON-native, since 2026-09-04)

**The user explicitly required tmplog to save directly as one JSON file — no Markdown.** Markdown files were retired and archived under `<LOGTMP_DIR>/legacy/pre-json-2026-09-04/`. Never recreate `today.md`/`history.md`/`days/*.md`, and never route writes through a Markdown intermediate.

### Portable storage-root resolution

Do **not** hard-code another product's directory (such as `~/.hermes/...`). Resolve `<LOGTMP_DIR>` in this priority order:

1. An explicit path supplied by the user for this agent/product.
2. A `LOGTMP_DIR` environment variable or equivalent per-skill configuration.
3. The current agent product's own documented private persistent-data root. Child location candidates (choose only the product's documented one): `<root>/workspace/logtmp/` (preferred for workspace products), `<root>/data/logtmp/`, `<root>/storage/logtmp/`, `<root>/state/logtmp/`, `<root>/logtmp/` (fallback).
4. If the product cannot determine its own private persistent-data root, ask the user for a directory before the first write.

### Storage discovery safety boundary (mandatory)

- **Never perform a whole-disk, whole-home, or broad recursive filesystem search** for an existing `logtmp`, `logtmp.json`, or `worklog.html`.
- Do not search another agent's/application's data, configuration, cache, workspace, Downloads, Desktop, Documents, or any other unrelated user directory to infer a storage location.
- Only a bounded existence check of the product-private candidates above is allowed.
- If the selected `<LOGTMP_DIR>` does not exist, create it immediately. Absence is not a reason to search elsewhere.
- If no safe product-private root is available, stop and ask the user for a path.

The resolved directory is `~/.workbuddy/workspace/logtmp/` for WorkBuddy. Files under `<LOGTMP_DIR>`:

- `<LOGTMP_DIR>/logtmp.json` — **single source of truth** (database).
- `<LOGTMP_DIR>/worklog.html` — derived read-only web view (JSON embedded inline; opens by double-click, no server, no CORS).
- `<LOGTMP_DIR>/update_webpage.py` — regenerates `worklog.html` from `logtmp.json`.
- `<LOGTMP_DIR>/legacy/` — retired pre-JSON Markdown data (do not touch unless recovering).

### logtmp.json schema

```json
{
  "schema": 1,
  "title": "logtmp 工作临时记录",
  "updated_at": "YYYY-MM-DD HH:mm:ss",
  "ongoing": [
    {"first_captured": "YYYY-MM-DD HH:mm", "reminder": "YYYY-MM-DD",
     "content": "...", "updates": [{"time": "HH:mm", "content": "..."}]}
  ],
  "days": {
    "YYYY-MM-DD": {
      "items": [
        {"time": "HH:mm", "content": "...", "report_status": "未上报",
         "reported_hours": 0, "reported_at": null, "record_id": null,
         "updates": [{"time": "HH:mm", "content": "..."}]}
      ],
      "reminders": ["..."]
    }
  }
}
```

Rules:

- `W$n` is a **positional identifier**: `days["YYYY-MM-DD"].items[n-1]` (index 0 → W1). Do not store `id` fields; assign W numbers in replies by array order.
- `ongoing` is top-level and cross-day by construction — there is **no daily reset**, nothing to clear, nothing to archive. Every day's records stay under its own date key forever.
- After **every** write/update/integration/check-that-changes-data, set `updated_at` and regenerate the web page: run the managed python:
  `/Users/zhou/.workbuddy/binaries/python/versions/3.13.12/bin/python3 <LOGTMP_DIR>/update_webpage.py`
  (script exists at that path; it rewrites `updated_at` itself). If it is ever missing, recreate it from the current `worklog.html`-generation logic before reporting success.
- Read the file with the Read tool before editing it (Write tool refuses stale writes). Preserve valid JSON at all times; after edits, quick-check that the file still parses (`python3 -c "import json;json.load(open('<path>'))"`) only if a runtime or the user requests verification — routine captures skip ad-hoc verification.
- The web page can locally mark items as reported and export an updated `logtmp.json`. Treat page exports as **drafts**: do not overwrite the store from them and do not treat them as company submissions unless Zhou explicitly confirms.

## Work-Hours Reporting Status

Every top-level same-day work item (`W$n`) must carry whether its log/hours have been reported to the company mylog system and how many hours were reported.

Rules:

- New `tmplog` top-level records default to `report_status: "未上报"`, `reported_hours: 0` unless the user explicitly says it was already reported.
- Historical items without reporting metadata are treated as **not reported**. Do not assume old records were reported just because they mention hours.
- For a `tmplog` item generated from a meeting transcript or meeting minutes, calculate a **建议上报工时** from the grounded meeting duration (round to half-hour granularity: 60-min meeting → 1h; 35-min → 0.5h). Keep it as a local recommendation only — `report_status: "未上报"` — never submit or locally mark it reported unless Zhou explicitly starts the company-work-hours submission workflow.
- Do **not** treat shorthand like `tmplog W1 上报工时1.5小时` as permission to locally mark the item submitted. It means a real company-system submission workflow unless he explicitly says `标记为已上报` / `本地标记`. Prepare a confirmation draft, submit only after confirmation, and update `logtmp.json` only after the add-log-record business success plus read-back verification.
- When a `W$n` item is successfully uploaded to mylog, update that item with `report_status: "已上报"`, concrete `reported_hours`, `reported_at`, and `record_id` (only if safe and useful; never write tokens/credentials).
- If a submission partially succeeds or fails, mark only the successful `W$n` items `已上报`; leave failed ones `未上报` and record the failure in a nested `updates` entry.
- If a `W$n` is uploaded multiple times intentionally, preserve prior evidence and update the total only after Zhou confirms whether the new submission is additional hours or a correction.

## Write Operations

### New standalone note

1. Get today's date (Asia/Shanghai).
2. Read `logtmp.json`.
3. Ensure `days["YYYY-MM-DD"]` exists; if not, create `{"items": [], "reminders": []}`.
4. Append `{"time": "HH:mm", "content": "<原文>", "report_status": "未上报", "reported_hours": 0, "reported_at": null, "record_id": null, "updates": []}` to `items`.
5. Set `updated_at`; regenerate `worklog.html`.

Use the user's original wording as much as possible; keep it short. Strip a leading `tmplog ` control prefix from the saved content (the note itself, not a control command, is what gets stored).

- Same standalone line repeated verbatim in one message = accidental duplicate; record once.
- Multiple short pasted lines with a trailing continuation word such as `继续`: normalize into one item using Chinese punctuation while preserving content. `继续` alone is not permission to execute external work and not an ongoing item by itself.
- Do not add Markdown formatting, inline-code backticks, tabs, or control characters into JSON content strings.

### Update / parent classification

If the user clearly means an update to a previous temporary item:

1. Read the relevant day's items from `logtmp.json`.
2. If the user explicitly names the parent (number or `W$n`), append to that item's `updates`: `{"time": "HH:mm", "content": "<更新内容>"}`.
3. If the parent is not explicit, list available parents and ask the user to choose. Do not write until confirmed.
4. Strip the control prefix/number from saved update text (`update W1` / `更新 1` are not stored).

Identifier conventions:

- Same-day top-level work items: `W1`, `W2`, ... (`W` = work) — positional in `days[date].items`.
- Ongoing follow-up items: `O1`, `O2`, ... (`O` = ongoing) — positional in top-level `ongoing`.
- Accept `W`/`O` prefixes case-insensitively; normalize to uppercase in replies.
- `update W2 ...` / `更新 W2 ...` / bare `W2 ...` when unambiguous → update to that same-day item. `update O3 ...` / `O3 ...` → update to that ongoing item.
- Bare number with both lists shown and target ambiguous → ask `Wn` or `On`.

When an update contains pasted stats/table-like text/tabs, normalize into one readable sentence preserving every concrete metric and unit (e.g. `统计完成：标准人员数 42 人；同步工时不一致数 20 组；禅道多出数 7 组`).

### Reparenting

Explicit reparenting such as `tmplog W6作为W2的更新记录` / `把 W6 放到 W2 下` / `W6 是 W2 的更新` is permission to move the existing top-level item under the named parent. Preserve the moved item's original time/content, append it to the parent's `updates`, remove the original top-level item, then return the renumbered W-list. Do not record the reparenting command as a new note; no extra confirmation when both identifiers are explicit.

### Similar work check & integration

- After writing a new standalone note, compare against same-day items. If clearly related (concrete shared objective/person/project/module/task chain — **not** mere shared labels like 禅道/工时/测试), ask whether to integrate. Use a card if available, else concise text. Do not merge without explicit agreement. If user says "不是一个事情", keep separate and don't re-ask for that pair without new evidence.
- Integration with explicit permission (e.g. `1,2,3,4 是一个事情/任务`, `1-4 合并成一个任务`): keep one consolidated top-level item, preserve original evidence/details as nested `updates` entries under it, remove the merged items, renumber downstream items. No second confirmation needed. There is no Markdown `## 合并整理` section anymore — grouped summaries live in the day's `reminders`-adjacent discussion or, if Zhou wants a persistent grouped view, add a `grouped` array on the day object (same style as a consolidated item) and keep it in sync. When in doubt, surface the consolidated wording in the reply for confirmation.
- If a merged item is an update of an ongoing item, also append it as a dated nested update under that ongoing item.

## 持续跟进事项 (ongoing)

Use for tasks that must be checked every day or across multiple days. Stored in top-level `ongoing` (never under a single day, so it survives forever — JSON has no daily reset).

Rules:

- Add when the user explicitly says `ongoing` / long-running / continuous / daily follow-up / must not be cleared. Recommended shorthand: `tmplog ongoing: ...`. Normalize typos like `onging` to `ongoing`.
- Each item needs `first_captured` (`YYYY-MM-DD HH:mm`) and `reminder` (`YYYY-MM-DD`). When the user adds an ongoing item without a clear reminder date, ask for it before writing (accept `2026-07-10`, `7月10日`, `明天`, `下周一`, `每天从明天开始`; normalize to `YYYY-MM-DD`). If the user provides one date for a whole batch, apply it to every item; otherwise ask.
- Keep each item actionable and short. Never put `reminder`/`first_captured` inside `content`; they are fields.
- Completion shorthand `tmplog O6 已完成` / `不用跟进了` / `取消`: sync a same-day note into today's `items` (e.g. content `ongoing更新/O6 已完成：...`), then remove that ongoing item. Do not leave a completed item active.
- Reminder-date backfill shorthand `tmplog O1 O3 周一提醒我` / `O10-O13 下周一提醒我`: resolve date in Asia/Shanghai, update `reminder` on those items, create no new raw notes.
- Ongoing item updates append to that item's `updates` **and** sync a same-day note into today's `items` so the day's view shows it.
- If `update ongoing` omits the number/name, list current ongoing items only and ask; a bare-number reply confirms the pending update. A reply like "这是一个新的" means create a new ongoing item (infer/ask reminder date).
- Do not delete or mark done unless the user explicitly says completed/cancelled/no longer followed.

## Ongoing Reminder Automation

- A daily scheduled job should scan top-level `ongoing` and emit reminders for every item whose `reminder` date is today or earlier. Stay silent when nothing is due.
- Reminders must reach the user through a gateway-connected delivery target (Telegram/Discord/Slack/Email, or `all` if fan-out requested) — do not claim reminders are active until a cron job with a real delivery target exists.
- Recommended schedule: `0 9 * * *` Asia/Shanghai.
- Suggested shape:

```text
tmplog 持续跟进提醒（YYYY-MM-DD）
- O3 我的日志未接通卡片需求整理（提醒日期：YYYY-MM-DD）
- O7 速记BUG修复（上传慢/失败、出原文慢等）（提醒日期：YYYY-MM-DD）
```

## Check Command

Use for `tmplog check`, `/tmplog check`, `check tmplog`, or summarize/check requests. Do not append `check` as a note.

Workflow:

1. Current date in Asia/Shanghai; read `logtmp.json`.
2. Summarize all current work from `days[<recent dates>].items` into concise work groups.
3. Read top-level `ongoing`; present unchanged unless the user requests a change.
4. Consider whether today's `reminders` need updating: add missing items for unresolved decisions, blocked next steps, pending confirmations, pending teamlog conversion, pending ZenTao creation, pending module/person/date confirmation, release follow-up.
5. Preserve existing valid reminders; do not delete unless the log proves them obsolete.
6. If reminders changed, edit only `days[today].reminders` (no other data touched).
7. Reply with: whether the file changed; work summary grouped by topic; ongoing list (`O1.`... one per line, blank line between items); same-day reminders; the `logtmp.json` path.

## Backdated Records & Updates

- Explicit backdate (`记录到7月20日的tmplog`, `补昨天W2`) → write into `days["YYYY-MM-DD"]` for that date (create the key if missing). No reset logic applies — every date key stands alone.
- Prefer updating the clearly related existing `W$n` item when the target parent is obvious from the conversation.
- Use the artifact/source time for nested updates when known (e.g. `14:13`) rather than the current wall clock.
- Backfilled standalone items get normal default reporting metadata (`未上报` / 0h), then reply with that day's full W-list.

## Work-Hours Backfill from Archived Tmplog

Use when the user asks to补工时 from a prior day, e.g. `昨天tmplog list` then `YYYY-MM-DD W1 记录工时 0.5`.

Workflow:

1. Resolve the date; show that day's W-list from `days[date].items`.
2. On `YYYY-MM-DD Wn 记录工时 <hours>`, create/update `<LOGTMP_DIR>/YYYY-MM-DD-hours.md` draft:

```markdown
# YYYY-MM-DD 工时补录草稿

| 序号 | 事项 | 工时 |
|---|---|---:|
| W1 | 事项标题 | 0.5 |

合计：0.5 小时
```

3. Same W recorded again → update the row, recalc the total.
4. Local draft only; no teamlog/ZenTao writes unless the user explicitly asks.

## Monthly or Date-Range Export

1. Primary source: `logtmp.json` (plus `YYYY-MM-DD-hours.md` drafts). Do not assume completeness without checking date-key coverage.
2. If data is missing, recover from `legacy/pre-json-2026-09-04/` Markdown or session history as secondary source; explain provenance in the export.
3. Export canonical top-level W items, folding `updates` and reporting metadata into the parent row. Merged labels like `W5/W8` may be used for export/事情分析 only — they never renumber the store's array order.
4. Deduplicate by date/time/normalized content/underlying activity; merge obvious workflow-artifact duplicates (转写→纪要 of one meeting) but not distinct work sharing broad words.
5. Reporting status comes only from explicit `report_status` fields or company-system read-back. Mentions of `1小时`/`3小时` do not make an item reported.
6. Include every calendar date in range, including explicit no-record days. Columns: date, W label, time, work content/updates, reported?, hours, meeting-summary path (validate against filesystem; write `未找到对应会议总结文件` when absent), notes.
7. Verify date coverage, canonical row count, reported/unreported counts, hour total, referenced paths, duplicate record IDs before delivery.

## Listing and Response

After every write, update, move, or integration, reply with:

1. One short confirmation and the file path.
2. A concise summary of the change.
3. The current full list of today's top-level items, numbered `W1.`, `W2.`, ... in physical array order under `days[today].items`. `W$n` is positional — never sort the reply differently from the stored order.
4. Nested `updates` shown under their parent.
5. Ongoing items numbered separately `O1.`, `O2.`, ... with a blank line between items (and after any nested updates) so clients do not collapse them.
6. If similar work exists and integration is not confirmed, ask whether to integrate.

The numbered list is required every time `logtmp.json` changes. When the user only asks for the list, return the numbered list and file path without modifying anything. If the user asks for the raw data, include the complete `logtmp.json` content in a fenced json code block.

If a note looks like it should later become a formal `teamlog`, mention it is only temporarily captured and can be整理到 `teamlog` later.

## Storage Path Changes

When the user asks to move `logtmp`: update this skill's storage paths first, then move `logtmp.json` (+ `update_webpage.py`, `worklog.html`, `legacy/`) to the new directory preserving content/permissions. Verify the new files are readable and no stale path reference remains before reporting success. Update durable memory/user-profile path references if they point at the old location. If cleanup of old directories is destructive or blocked, report exactly what remains.

## Boundaries

- Do not write formal `teamlog` from tmplog unless the user explicitly asks.
- Do not create or edit ZenTao tasks from tmplog unless the user explicitly asks.
- Do not ask for project/module confirmation for plain tmplog capture.
- For actual ZenTao task creation, follow the separate ZenTao module-confirmation rule and never infer the module automatically.
- Never reintroduce Markdown storage files unless the user explicitly reverses the 2026-09-04 JSON decision.
