# Batch identity, evidence and reconciliation

## Manifest contract

Use a JSON manifest for single or batch runs. Store it after discovery and update after each item/small batch so interrupted work can resume. It is a processing ledger, not a provider response.

Top-level fields: `schema_version`, `run_timestamp`, `source_files`, `requested_scope`, `sync_approval_scope`, `records`.

For each input meeting record store:
- `record_id`: unique within run; `source_type`: audio, provided_transcript or existing_asr.
- `source_locator`: exact file/row/record index; optional literal `room_id`, `event_ts`.
- `original_path`, `original_sha256`, `normalized_transcript_path`, `content_sha256`.
- `meeting_key`, `meeting_start`, `meeting_end`, `timezone`, `time_source`, `time_semantics`, `duration_value`, `duration_unit`; unresolved values null, not guessed.
- `disposition`: pending, processed, duplicate, empty, failed or blocked; `reason`; `duplicate_of` when applicable.
- `topic`, `minutes_path`, `minutes_result`: created, reused or null.
- `chunk_coverage`: source intervals read and unresolved gaps, where chunking is used.
- `tmplog_status`: not_requested, awaiting_approval, existing, written, failed or blocked; `tmplog_target` and stable source marker.

Archive malformed records before marking failed/blocked. A record lacking a date can still have minutes while its log status is blocked. Never put credentials or signed URLs in this manifest.

## Stable identity is not a summary hash

Compute hashes with a tool from actual bytes/data. Keep original-byte SHA-256 separate from normalized-content SHA-256. Do not hash an LLM summary for stable identity: wording changes between runs.

Prefer a provider's stable meeting-instance ID. A room_id can be reused; combine with a supported occurrence/start marker rather than assuming room_id alone is unique. Preserve literal source identifiers and validate format; do not repair them.

Fallback identity uses deterministic transcript content (fixed field order, UTF-8, stable JSON serialization of text/speaker/relative-time fields) plus supported meeting occurrence metadata. Record the normalization version. Source file/row locators establish provenance but do not by themselves detect the same meeting exported into another file.

Duplicate tiers:
1. Same stable instance and matching content: reuse.
2. Same source-byte hash + row/record locator: same imported item.
3. Same normalized content with compatible time/participants: strong duplicate candidate; verify context, especially generic/short calls.
4. Similar topic/time/participants only: candidate, not automatic duplicate. Timestamp tolerance only assists matching; record the tolerance and evidence. No silent fuzzy deletion.

Same instance with different content may be a corrected or extended transcript: preserve both originals, identify the new revision and update/review existing minutes rather than dropping new evidence. Repeated meetings about the same ongoing issue are separate occurrences; log new outcomes instead of skipping the issue entirely.

## Structured input handling

- TSV: use csv.DictReader with tab delimiter and newline-aware quoted-cell parsing; retain row locators and parse nested JSON separately.
- conversation_json: preserve received raw representation. If only a decoded object is available, label the serialization as captured structured data, not byte-identical original export.
- Paired files: include numbered suffix in pairing. Validate date/participants where available; matching generic titles alone is insufficient.
- Ending timestamps: subtract duration only after verifying end-time semantics and duration units. Preserve original values beside derived ones. Convert with timezone-aware code; keep cross-midnight start/end distinct.
- Long content: enumerate all meetings first, then process bounded contiguous chunks per meeting and persist results. Finish required child work before claiming coverage.

## Reconciliation

Use mutually exclusive record dispositions. Assert in code:

`input_record_count == pending + processed + duplicate + empty + failed + blocked`

For normal per-meeting scope, every processed record must point to nonempty individual minutes and every duplicate must point to a known canonical record. Compute created/reused counts from distinct canonical meeting identities, not directory-wide globs. Count log writes independently from processed records; not-requested/awaiting approval is not written. List pending/failed/blocked records and why.

Resume using source identity and recorded artifact checks, not new timestamps alone. Reuse completed minutes/transcripts, process remaining items, and avoid repeated paid ASR. If previously linked artifacts need a migration, preserve originals and update references under explicit migration scope rather than silently moving them.
