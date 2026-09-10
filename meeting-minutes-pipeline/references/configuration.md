# Runtime configuration

This package is instructions, not an installed transcription service. No credentials, personal data, executable helper or log backend are bundled.

Resolve these values from explicit user input or documented host configuration. Ask only for values required by the selected route. Do not invent credentials or scan unrelated private directories.

| Parameter | Requirement |
|---|---|
| workspace_root | Writable task workspace supplied by the caller/host; no fixed home path |
| artifact_root | Optional; defaults relative to workspace_root as `asr`, for compatibility; caller may override |
| asr_dir, source_dir, minutes_dir, manifest_dir | Optional writable paths; relative defaults under artifact_root are ASR, sources, 会议纪要, manifests; names are organizational defaults, not machine dependencies |
| processing_timezone | Explicit IANA timezone or documented host timezone; if absent ask before creating dated run names |
| source_timezone | Used for timezone-naive meeting times; do not silently assume it equals processing_timezone |
| output_language | User-requested language, otherwise language of the current request |
| asr_adapter | Required only for media without a reusable transcript; documented tool/API/command |
| log_adapter | Optional; required only for approved log writes |
| task_adapter | Optional; required only for explicitly approved task creation |

At run start report the resolved output root and routes. Use portable filesystem/path APIs, UTF-8 and supported host tools. No shell, Python installation, ffprobe installation, network access or package manager is guaranteed. Use equivalent host capabilities where available; explain a blocker when not.

Secrets must be obtained through the host secret manager/environment integration and never copied into this package, manifests or examples. Do not install integrations or upload recordings unless the user authorized that processing destination. Existing text requires no cloud upload.

The skill name and relative bundled reference paths are intentionally stable identifiers. Other skills named in historical material are not dependencies of this export.
