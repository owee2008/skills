# Optional log adapter

No log backend is assumed. Without an adapter, complete minutes and report approved synchronization as blocked; provide a draft for the user if useful, but never claim it was written.

Before use establish documented operations for search, date routing, create/update and verification, plus the actual target store. Logical fields: stable meeting identity, source date/time, topic, micro-summary, individual minutes path, existing record ID and optional user-requested hours. Do not require a particular file layout or W/O numbering. W identifiers apply only if the configured system supports them; otherwise ask for an actual target ID.

Explicit sync approval is mandatory. Batch approval covers only the specified batch. Search existing records by identity and provenance before writing; repeated topics alone do not establish duplication. Preserve unrelated existing content.

Read back exact targets after external writes. On ambiguous timeout, search by stable identity before retrying. For local files, use the host's confirmed-write policy and batch reconciliation. Preserve each result in the manifest.

No log request authorizes company timesheet submission, tickets, notifications or reminders. Hours require a user request and supported measurement; never convert recording length automatically to actual work. If the user requests ongoing reminders, require a reminder date and a separate configured scheduling integration.
