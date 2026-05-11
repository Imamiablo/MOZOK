# MOZOK

MOZOK is a reusable bot-brain backend for agents, NPCs, narrators, assistants, and similar systems.

Current core stack:

- FastAPI API layer
- PostgreSQL as the source of truth
- FAISS semantic memory index
- sentence-transformers embeddings
- Ollama/OpenAI-compatible LLM calls
- Long-term memory: raw, episodic, semantic, core
- Short-term per-session RAM memory
- ContextBuilder prompt assembly
- Debug context endpoint
- Lorebook/world knowledge, entity states, goals/plans, knowledge relations, procedural skills
- Brain pack / scenario import

## Local setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Create a local `.env` from `.env.example`, then start PostgreSQL and initialise the DB:

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Open Swagger UI after starting the API:

```text
http://127.0.0.1:8000/docs
```

Some HTTP smoke tests need a real running Mozok API and are skipped automatically if it is not reachable.
