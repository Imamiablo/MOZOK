# Mozok

**Mozok** is a reusable Python bot-brain engine prototype.

It is designed as a core that can later be connected to:

- chat bots
- game NPCs
- desktop pets
- RPG simulations
- document/RAG-style assistants

Current stack:

- **FastAPI** for the API
- **PostgreSQL** as the source of truth
- **FAISS** as a fast vector search index
- **SQLAlchemy** for database access
- **Ollama OpenAI-compatible API** for LLM responses
- **sentence-transformers** for local embeddings

---

## Big idea

PostgreSQL stores the real memory records.

FAISS stores a fast vector index.

If FAISS breaks or goes out of sync, it can be rebuilt from PostgreSQL.

```text
User/Game/Event
    ↓
FastAPI
    ↓
BotCore
    ↓
MemoryService
    ├── PostgreSQL = source of truth
    └── FAISS      = semantic search index/cache
```

---

## Requirements

Install Docker Desktop first if you want the easy PostgreSQL setup.

Then install Python dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Configure

Copy environment example:

```bash
copy .env.example .env
```

On Linux/macOS:

```bash
cp .env.example .env
```

---

## Start PostgreSQL

```bash
docker compose up -d
```

This creates:

- database: `mozok`
- user: `mozok`
- password: `mozok`
- port: `5432`

---

## Create tables

```bash
python scripts/init_db.py
```

---

## Seed demo memories

```bash
python scripts/dev_seed.py
```

---

## Run API

```bash
uvicorn mozok.api.main:app --reload
```

Open:

```text
http://127.0.0.1:8001/docs
```

---

## Test with curl

Add a memory:

```bash
curl -X POST http://127.0.0.1:8001/memories ^
  -H "Content-Type: application/json" ^
  -d "{\"agent_id\":\"cat_001\",\"content\":\"Denys likes bots that feel alive and remember past events.\",\"memory_type\":\"fact\",\"importance\":7}"
```

Search memories:

```bash
curl -X POST http://127.0.0.1:8001/memories/search ^
  -H "Content-Type: application/json" ^
  -d "{\"agent_id\":\"cat_001\",\"query\":\"What does Denys like in bots?\",\"limit\":5}"
```

Chat:

```bash
curl -X POST http://127.0.0.1:8001/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"agent_id\":\"cat_001\",\"message\":\"What do you remember about what I like?\"}"
```

---

## Ollama setup

By default Mozok expects:

```text
http://127.0.0.1:11434/v1
```

Configure the model in `.env`:

```env
OLLAMA_MODEL=qwen2.5-coder:32b
```

You can change it to any model you have in Ollama.

---

## Current limitations

This is a clean skeleton, not a finished production system.

Missing or simplified:

- robust migrations via Alembic
- full FAISS deletion/update compaction
- background index rebuild jobs
- authentication
- relationship memory scoring
- proper reranker
- long document ingestion pipeline
- multi-agent planning loop
