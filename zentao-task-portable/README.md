# Portable ZenTao Task Skill

This package is an export of the `zentao-task` skill for use by other agents.

## Install

Copy the directory into the target agent's skills directory, retaining its name, or unzip the archive and configure that agent to load `SKILL.md`.

## Required path configuration

Before any command that generates a screenshot, backup, or browser snapshot, set an agent-owned workspace. No output is written into the skill installation directory.

```bash
export ZENTAO_WORKSPACE_DIR="/path/to/this-agent/workspace"
# Optional: point to a Python interpreter that has Playwright installed.
export ZENTAO_PLAYWRIGHT_PYTHON="/path/to/python"
# Optional: only if the query script must clean a browser lock in its own profile.
export ZENTAO_BROWSER_PROFILE_DIR="/path/to/browser-profile"
```

Precedence for generated files: `ZENTAO_WORKSPACE_DIR` → `HERMES_WORKSPACE` → current working directory. Outputs are placed below `zentao-artifacts/` and backups below `zentao-change-backups/`.

## Credentials

The scripts expect ZenTao credentials from HashiCorp Vault via `VAULT_ADDR` and `VAULT_TOKEN`; credentials are not included in this export.
