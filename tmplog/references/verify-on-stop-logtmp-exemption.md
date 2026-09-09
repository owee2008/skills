# logtmp verify-on-stop exemption

Context: routine `tmplog` writes are markdown note captures under `<LOGTMP_DIR>/`, not code changes. In coding-agent/TUI sessions Hermes may inject a verify-on-stop nudge after file edits. The user explicitly accepted routine tmplog updates without proactive ad-hoc verification.

Implemented pattern in Hermes core:

- Add a path predicate for `get_hermes_home() / "workspace" / "logtmp"`.
- Filter ignored paths before marking verification evidence stale in `agent/verification_evidence.py::mark_workspace_edited`.
- Filter ignored paths before building the stop nudge in `agent/verification_stop.py::build_verify_on_stop_nudge`.
- Keep normal verification behavior for real project/code files.

Regression tests to preserve the behavior:

- `tests/agent/test_verification_stop.py::test_logtmp_edits_do_not_request_verification`
- `tests/agent/test_verification_evidence.py::test_logtmp_edit_does_not_stale_verification`

Canonical verification used during the session:

```bash
uv run --extra dev pytest tests/agent/test_verification_stop.py tests/agent/test_verification_evidence.py -q
uv run --extra dev ruff check agent/verification_evidence.py agent/verification_stop.py tests/agent/test_verification_stop.py tests/agent/test_verification_evidence.py
scripts/run_tests.sh tests/agent/test_verification_stop.py tests/agent/test_verification_evidence.py
```

Pitfall: On macOS, pytest temp dirs may resolve under `/private/var/...`; existing file-tool tests that write through `write_file_tool` can hit sensitive-path protection. If the test is about verification state rather than path safety, monkeypatch `tools.file_tools._SENSITIVE_PATH_PREFIXES` inside that test instead of weakening production path protection.

Operational note: Hermes code changes may require restarting the desktop/TUI process before the current runtime adopts the new exemption.