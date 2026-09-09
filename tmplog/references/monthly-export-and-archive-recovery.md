# Tmplog Monthly Export and Archive-Recovery Playbook

Use this reference when exporting a month/date range, especially when `history.md` has been overwritten, rebuilt, or contains duplicate snapshots.

## Source priority

1. Read the live files first: `today.md`, `history.md`, and any `YYYY-MM-DD-hours.md` drafts.
2. Discover other files under the active `logtmp/` directory before concluding the source set is complete.
3. If persisted history is incomplete, use Hermes session history only as a secondary recovery source. Prefer historical tool read-backs of the actual `today.md`/`history.md` over assistant prose.
4. Label recovered rows and explain the recovery provenance in the export.

## Canonicalization

- Parse only top-level work items as exported rows; fold nested updates and reporting metadata into the parent.
- Preserve the original physical W identifier where possible. For merged duplicates, retain provenance such as `W5/W8` or `W1/补录W1`.
- Deduplicate by date, time, normalized content, and underlying issue/meeting identity—not by text alone.
- Merge obvious workflow-artifact duplicates (for example: meeting discussion, transcription generated, summary generated) into one canonical meeting row while preserving the source labels and meaningful updates.
- An item accidentally stored under `## 合并整理` can be recovered only when historical evidence explicitly showed it as a W item; annotate this correction.

## Reporting status

- Explicit metadata or company-system read-back is authoritative.
- Text such as `1小时`, `3小时`, or `工时补录` is not evidence of submission.
- If metadata is absent, export `未上报 / 0h`.
- Failed, invalid, or non-readable submissions do not count. If a later submission was read back successfully, count only the verified amount.
- Deduplicate repeated record IDs that appear in both metadata and nested updates.

## Meeting summaries

- Treat explicit meeting, weekly-meeting, discussion, review, or meeting-summary records as meeting/discussion items; do not classify ordinary feature names containing the word “会议” as an actual meeting without context.
- Use paths explicitly attached to the item first; then match exact date/topic filenames where confidence is high.
- Validate every output path against the current filesystem. Never invent a path.
- A meeting may legitimately have multiple summary files (for example, an original summary and a later regenerated summary); include every verified relevant path.
- If no verified match exists, write `未找到对应会议总结文件` rather than omitting the field.

## Output and verification checklist

- Include every calendar date in the requested range, with explicit no-record dates.
- Required columns: source W label, time, work content/updates, reported status, reported hours, meeting-summary path, notes.
- Include summary totals: canonical item count, days with/without records, reported/unreported item counts, verified reported-hour total, meeting count, meetings with/missing summaries.
- Re-read the artifact and mechanically verify: all date headings, main-row count, reported-hour sum, all referenced paths exist, and no repeated adjacent record IDs.
- Deliver the file path and a concise summary, including the list of meetings whose summary file was not found.
