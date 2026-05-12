# MOZOK ROADMAP

## Current status after version 33

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
- Context Budget Policy V2
- Dedup V2 audit
- Knowledge Relations V3 graph intelligence
- Procedural Skills V3 learning and shared skill libraries
- Cognitive Field MVP resonance/competition/broadcast layer

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
- one-hop and optional multi-hop relation expansion
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

### Cognitive Field MVP

- Optional deterministic candidate-thought generation.
- Scores attention, sensory weight, memory resonance, goal relevance, emotional weight, procedural skill relevance, relation support, contradiction penalty, risk penalty, and confidence.
- Supports transient `sensory_inputs` for game/world/tool/UI signals.
- Selects a read-only conscious-broadcast-style focus for the current turn.
- Can be injected into `/debug/context` and `/chat` through opt-in request fields.
- Dedicated read-only debug endpoint: `POST /agents/{agent_id}/cognition/field/debug`.
- Does not claim biological or phenomenal consciousness and does not mutate memories, goals, skills, relations, or entity states by itself.

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

### Dedup V2

- Language-aware prompt-time memory dedup tokenisation for English, Ukrainian, Russian, and simple CJK text.
- Read-only `POST /agents/{agent_id}/memory-dedup/audit` endpoint.
- Audit combines normalised text similarity, token overlap, and optional embedding similarity.
- Reports `duplicate_of`, `similar_to`, `supersedes`, and `contradicts` candidates.
- Returns suggested KnowledgeRelation-style payloads without creating graph edges automatically.
- No automatic deletion, archiving, merging, FAISS mutation, or SQL mutation.
- OpenAPI and unit coverage for audit schemas, relation suggestions, contradiction detection, superseding detection, and embedding-similar candidates.

### Knowledge Relations V3

- Read-only `POST /agents/{agent_id}/knowledge-relations/graph/debug` endpoint.
- Multi-hop traversal from explicit root nodes.
- Cycle detection with reported paths instead of infinite graph following.
- Budget-aware traversal by max depth, max relations, per-node limit, and optional approximate token budget.
- ContextBuilder support for `knowledge_relation_traversal_depth` and `knowledge_relation_traversal_token_budget`.
- Relation-aware reranking now includes a small second-hop graph signal.
- Reviewed relation creation endpoint: `POST /agents/{agent_id}/knowledge-relations/auto-create`.
- Maintenance/summarisation now creates conservative provenance edges: `summarised_by` and `derived_from`.

### Procedural Skills V3

- Skill usage/result tracking through `POST /procedural-skills/{skill_id}/usage-results`.
- Per-skill effectiveness stats: usage count, success/failure/neutral counts, success rate, average score, and last-used timestamp.
- Learned strategy notes stored as evidence; optional explicit `apply_learned_note` copies a safe note into visible skill notes.
- Built-in skill templates exposed through `GET /procedural-skills/templates`.
- Template-to-agent creation through `POST /agents/{agent_id}/procedural-skills/from-template`.
- Shared library skills under `__shared__`, opt-in through `include_shared` / `include_shared_procedural_skills`.
- Skill relation suggestions and reviewed graph sync for goal/lore/entity links.
- ContextBuilder, `/chat`, and `/debug/context` support opt-in shared procedural skills without changing existing default isolation.

## Immediate cleanup status

- `.gitignore` restored/updated.
- `.venv`, `.idea`, `__pycache__`, `.pytest_cache`, logs, FAISS index files, and installer EXEs are ignored.
- Stray patch history under `mozok/docs/patch_history` was consolidated into `docs/patch_history`.
- `ROADMAP.md` added as the current plan document.
- `requirements.txt` and `requirements-dev.txt` restored/updated.
- Full pytest run passes in the previous review environment: 145 passed, 3 skipped. Version 33 adds focused Cognitive Field tests; run full pytest locally after installing dependencies.

## Known non-blocking warnings / checks

- Pydantic v2 warns that class-based `Config` is deprecated. This is not breaking now, but should be cleaned before a future Pydantic v3 migration.
- The 3 skipped tests are real HTTP smoke tests. They require a running local Mozok API and should be checked manually through Swagger UI / running server.
- Brain-pack memory import uses MemoryService after structural scenario sections. Embeddings and FAISS writes are owned by MemoryService; they are not rolled back by the scenario-section transaction wrapper.

## Roadmap V2 candidates

### 1. Safe Change Proposals / Approval Engine

- Generic change proposals for memory, goals, skills, entity states, relations, and future action plans.
- Modes: manual review, apply low-risk changes, auto-apply with rollback snapshot, dry-run only.
- Unified preview/apply/reject result format so users can approve changes efficiently.
- Guardrails so automatic learning cannot silently damage long-term state.

### 2. Agent Mode Profiles

- Modes such as assistant, roleplay_character, simulacra_npc, narrator, world_director, tutor, and tool_agent.
- Mode-specific defaults for lore visibility, entity-state kinds, relationship modelling, cognitive-field weights, and allowed actions.

### 3. Self-Model / Reflective State

- A functional self-model, not a consciousness claim.
- Assistant agents track task understanding, uncertainty, user-preference fit, limitations, and recent mistakes.
- NPCs track identity, perceived situation, social mask, current intention, and emotional/social state.
- Narrators track scene tension, pacing, unresolved plot hooks, and dramatic focus.

### 4. Reflection and Learning Loop

- After each response/action, evaluate what happened, whether goals were served, whether memories or skills should be updated, and whether contradictions appeared.
- Produce safe change proposals instead of mutating important state directly.

### 5. Action Planning / Tool Intent Layer

- Represent intended actions separately from text replies.
- Support assistant tools, game commands, narrator events, and world updates through reviewed action plans.

### 6. Belief Revision / Contradiction Handling

- Convert Dedup V2 contradiction/supersedes signals into state-update proposals.
- Weaken, contextualise, or supersede outdated beliefs instead of keeping every memory equally active.

### 7. Agent Runtime Tick MVP

- Let simulacra/NPC agents act between user messages.
- Tick loop: retrieve context, run cognitive field, choose intention/action, reflect, propose safe updates.

### 8. World Event Bus

- Standard event records for game/app integrations: location changes, sounds, visual observations, social events, tool observations, and system events.
- Events can feed sensory inputs, episodic memory, goals, skills, and entity states.

### 9. Evaluation Packs V2

- Extend scenario regression packs to check cognitive broadcasts, expected actions, emotional/entity-state changes, and forbidden leakage.

## Deferred development priorities

### 1. Maintenance V3

- FAISS direct mutation
- LLM decision-maker for maintenance
- advanced cluster-to-relation auto-creation
- stored suggestion history table
- UI controls for apply/reject all
- advanced semantic duplicate merging

### 2. Reranking V2

- LLM reranker
- cross-encoder reranker
- user-tunable weights
- per-agent reranking profiles
- more advanced relation graph scoring
- evaluation dataset for ranking quality


### 9. Cognitive Field MVP - DONE

- candidate thoughts
- attention competition
- memory resonance
- goal relevance
- procedural skill relevance
- sensory input support
- conscious-broadcast-style prompt guidance

### 10. Perception Layer MVP - DONE

- adapter-neutral event input
- deterministic event → sensory input compiler
- direct sensory inputs preserved
- perception profile for channel weighting/filtering
- `/perception/compile` endpoint
- integration with `/chat`, `/debug/context`, and Cognitive Field debug
