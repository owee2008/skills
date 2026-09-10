# ASR adapter contract

Use only a configured adapter with documented arguments, authentication, upload destination, result format and polling behavior. Discover its real help/schema before invocation. Do not assume a local helper script exists or copy command flags from another provider.

1. Validate real media with a supported media inspection tool. If missing, do not treat icons as audio; request the real source or report the inspection limitation.
2. Confirm cloud upload is within user-authorized scope and obtain credentials via host facilities.
3. Call the adapter using its actual schema. Speaker diarization, language hints, polling intervals and timeouts are configurable and only sent when supported.
4. Persist genuine returned job IDs/results privately. Resume a known job after ambiguous timeouts instead of blindly submitting another paid request.
5. Save a nonempty normalized transcript with speaker/time provenance and archive genuine provider responses.
6. If the provider has no separate task JSON, mark that artifact not applicable. Never synthesize provider statuses/results to fill an expected filename. Name genuine result archives according to their type, recording paths in the manifest.
7. Verify terminal job/subtask results when applicable. A local command failure after real provider success requires artifact inspection; do not invent successful output.

If unavailable, audio transcription is blocked; offer user-supplied transcript as a route, not fabricated data. Already supplied text bypasses this adapter entirely.

Signed URLs and access tokens are private. In manifests/minutes expose local safe paths and redacted status only.
