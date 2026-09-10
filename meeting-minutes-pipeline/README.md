# Portable Meeting Minutes Pipeline

Copy this entire `meeting-minutes-pipeline` directory into your agent's supported skill directory, or supply SKILL.md as instructions and expose all references alongside it. Installation location is determined by your agent, not this package.

Start with `references/configuration.md`. Supply a writable workspace, processing/source timezones as needed, and optional ASR/log adapters. The included minutes template makes text processing standalone. The package does not include ASR services, credentials, runnable provider helpers or a log backend.

Supported sources: audio/video (configured adapter), TXT, TSV, JSON/conversation_json, paired transcript/minutes and existing transcripts. Default output: individual meeting minutes, original evidence, normalized text and a resumable manifest. Log writes require explicit approval.

Example request (replace placeholders with actual values):
“Use this skill. Process the attached transcripts into individual minutes. workspace_root=<writable task directory>; processing_timezone=<IANA timezone>; source_timezone=<source timezone>; output_language=<language>. Do not sync logs.”

Portability changes: removed Hermes profile/home paths, fixed timezone, private helper commands and mandatory companion skills. `tmplog` remains only a compatibility term; it is not required. Relative output directory names are configurable defaults. No historical meetings or credentials are included.
