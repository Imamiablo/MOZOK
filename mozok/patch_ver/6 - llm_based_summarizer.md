# Patch 5 — LLM-based memory summarizer

This patch upgrades Mozok's memory maintenance/sleep cycle.

Before this patch, `_create_summary_memory()` made deterministic summaries by listing source notes.
That was safe, but noisy.

Now Mozok uses `mozok/memory/summarizer.py`:

- tries to use the configured local LLM through `OllamaOpenAIClient`;
- asks the model to turn raw memories into compact semantic notes;
- stores summary metadata such as `summary_method`, `summary_model`, and possible `summary_error`;
- falls back to deterministic summaries if Ollama/model access fails.

## Files changed

- `mozok/memory/summarizer.py` — new summarizer module.
- `mozok/memory/service.py` — `_create_summary_memory()` now uses `MemorySummarizer`.
- `mozok/memory/policy.py` — default policy now has a `summarizer` section.
- `mozok/llm/ollama_openai.py` — `.chat()` now accepts a `temperature` argument.

## Policy controls

You can tune summarization through the existing memory-policy endpoint:

```json
{
  "memory_policy": {
    "summarizer": {
      "enabled": true,
      "fallback_to_deterministic": true,
      "max_source_memories_for_llm": 30,
      "max_chars_per_source_memory": 600,
      "max_summary_chars": 1800,
      "temperature": 0.2
    }
  }
}
```

## Testing

Create several raw memories for an agent, then run:

```text
POST /agents/{agent_id}/memory-maintenance
```

with:

```json
{
  "trigger": "manual",
  "rebuild_index": true
}
```

Then search semantic memories. The created summary should have metadata like:

```json
{
  "summary_method": "llm",
  "summary_model": "...",
  "source_memory_ids": [...]
}
```

If Ollama is closed or the model fails, summary method may be:

```text
deterministic_fallback
```

That is expected and means maintenance did not crash.
