# MOZOK ROADMAP

## Current status after version 28

MOZOK is a reusable bot-brain backend built around:

- FastAPI API layer
- PostgreSQL as source of truth
- FAISS semantic memory index
- sentence-transformers embeddings
- Ollama/OpenAI-compatible LLM calls
- long-term memory: raw / episodic / semantic / core
- short-term per-session RAM memory
- ContextBuilder for prompt assembly
- debug context endpoint
- safe retrieval-time deduplication
- token budget MVP
- entity states
- lorebook/world knowledge
- goals/plans
- knowledge relations
- procedural skills
- brain pack / scenario import
- scenario evaluation suite

## Implemented MVP features

### Memory

- SQL-backed memory records
- FAISS indexing and search
- memory levels: raw, episodic, semantic, core
- legacy memory type aliases
- add/search/delete/forget endpoints
- access_count tracking
- memory policy per agent
- maintenance triggers
- LLM-based summariser with deterministic fallback
- FAISS rebuild endpoint

### Short-term memory

- in-process RAM session memory
- isolated by agent_id + session_id
- clear session / clear agent
- included in ContextBuilder

### Context system

- ContextBuilder
- final system prompt generation
- core/semantic/episodic/raw memory selection
- goals integration
- procedural skills integration
- lorebook integration
- entity state integration
- knowledge relation integration
- one-hop relation expansion
- safe context dedup
- token budget trimming
- debug pipeline steps
- deterministic reranking metadata and final prompt ordering

### Debugging

- POST /debug/context
- full prompt preview
- used memory IDs
- used goal IDs
- used skill IDs
- used lorebook IDs
- used entity state IDs
- used relation IDs
- dedup details
- token budget report
- pipeline steps
- reranking report in debug output and final prompt pipeline step

### World / agent knowledge

- Lorebook entries
- public/restricted/narrator_only visibility
- per-agent lorebook knowledge
- EntityState for social/user/narrative/faction/quest state
- Goals/plans as separate first-class records
- KnowledgeRelation graph edges

### Procedural skills

- skill CRUD
- trigger/procedure/examples fields
- relation to goals/entities/lorebook
- deterministic V2 selector by keywords/goals/lore/entity
- standalone selection endpoint
- selector fields forwarded through /chat and /debug/context

### Brain packs

- JSON/YAML brain pack import
- Markdown/TXT lorebook import
- dry-run mode
- atomic import mode for structural scenario sections
- relation node preflight validation
- imports agents, lorebook, agent lore knowledge, entity states, goals, procedural skills, knowledge relations
- indexed memory import through MemoryService, including embedding/FAISS path
- memory import dry-run preview and created ID reporting
- duplicate protection for exact same agent/type/content

### Scenario evaluation suite

- Reusable `mozok.scenario_evaluation` runner for context regression cases
- Scenario fixtures under `tests/fixtures/brain_packs`
- Brain pack import → indexed memory import → ContextBuilder evaluation coverage
- Checks for required/forbidden prompt text
- Checks for required/forbidden memory text
- Checks for lorebook, goal, procedural skill, entity-state, and relation integration
- Cross-agent leakage checks for restricted lore and memories
- Debug pipeline-step coverage for final scenario contexts

### Maintenance V2

- Memory policy per agent
- Forget actions: decay, archive, summarise, summarise_then_archive, soft_delete, hard_delete, protect
- Real maintenance pass
- Raw memory summarisation and archive
- Episodic decay
- Low-retention archiving
- Memory limit pressure handling
- LLM summariser with deterministic fallback
- FAISS rebuild after destructive maintenance
- Read-only maintenance suggestions / preview
- Relation-aware maintenance protection
- LLM-assisted explanation of suggestions
- Embedding/text clustering for similar memory groups as suggest-only
- Apply/reject service and schemas
- Apply/reject API endpoints connected and covered by OpenAPI tests

### Context Budget Policy V2

- Model-aware approximate token estimation via `token_estimation_model`.
- Optional explicit per-section budgets through `section_budget_tokens`.
- Section-level budget reports in `/debug/context` and `/chat` context budget output.
- Request-local prompt compression for oversized budgeted sections without mutating SQL memories.
- Deterministic short-term summarisation when old chat turns would overflow the prompt.
- Budget-aware one-hop knowledge-relation expansion cap.
- Backwards-compatible legacy total-budget trimming when no explicit section budgets are supplied.

## Immediate cleanup status

- `.gitignore` restored/updated.
- `.venv`, `.idea`, `__pycache__`, `.pytest_cache`, logs, FAISS index files, and installer EXEs are ignored.
- Stray patch history under `mozok/docs/patch_history` was consolidated into `docs/patch_history`.
- `ROADMAP.md` added as the current plan document.
- `requirements.txt` and `requirements-dev.txt` restored/updated.
- Full pytest run passes in the review environment: 129 passed, 3 skipped.

## Known non-blocking warnings / checks

- Pydantic v2 warns that class-based `Config` is deprecated. This is not breaking now, but should be cleaned before a future Pydantic v3 migration.
- The 3 skipped tests are real HTTP smoke tests. They require a running local Mozok API and should be checked manually through Swagger UI / running server.
- Brain-pack memory import uses MemoryService after structural scenario sections. Embeddings and FAISS writes are owned by MemoryService; they are not rolled back by the scenario-section transaction wrapper.

## Next development priorities

### 1. Dedup V2

Improve dedup beyond text similarity:

- embedding similarity
- language-aware tokenisation
- duplicate/similar/supersedes/contradicts relations
- audit endpoint
- never hard-delete automatically

### 2. Knowledge Relations V3

Add graph intelligence:

- multi-hop traversal
- cycle detection
- relation-aware reranking
- budget-aware traversal
- auto-created relations from maintenance/summariser
- graph debug endpoint

### 3. Procedural Skills V3

Make skills learnable/updatable:

- success/failure tracking
- learned strategies from experience
- shared skill libraries
- skill templates
- skill relation graph integration

### 4. Maintenance V3

- FAISS direct mutation
- LLM decision-maker for maintenance
- advanced cluster-to-relation auto-creation
- stored suggestion history table
- UI controls for apply/reject all
- advanced semantic duplicate merging

### 5. Reranking V2

- LLM reranker
- cross-encoder reranker
- user-tunable weights
- per-agent reranking profiles
- more advanced relation graph scoring
- evaluation dataset for ranking quality
