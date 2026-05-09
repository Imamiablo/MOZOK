# Patch 13 - Automated tests MVP

Adds a lightweight pytest test suite for the memory/context work completed so far.

Covered areas:

- short-term memory session isolation and clearing;
- safe context dedup: core wins over near-duplicate semantic memory;
- safe context dedup: specific episodic events are not collapsed into broad semantic patterns;
- context token budget trimming order;
- core memory trimming only as explicit last resort;
- ContextBuilder read-only debug contract via `update_memory_access=False`;
- debug `pipeline_steps` shape and counts.

These are unit tests only. They do not require PostgreSQL, FAISS, Ollama, or Docker.

Run from the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```
