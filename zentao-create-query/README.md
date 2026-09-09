# ZenTao Create + Query Skill Export

Install this folder in another agent's skill directory as `zentao-create-query/`.

Contents:

- `SKILL.md` — operational instructions and write-safety gates
- `scripts/zentao_common.py` — ZenTao HTTP/Vault client
- `scripts/zentao-list-projects.py` — project query
- `scripts/zentao-list-modules.py` — module query
- `scripts/zentao-query-task.py` — task-detail query
- `scripts/zentao-create-task-refactored.py` — task creation
- `requirements.txt` — Python dependency

The package contains no credentials or exported session cookies. Configure Vault and endpoint variables in the target agent's environment.
