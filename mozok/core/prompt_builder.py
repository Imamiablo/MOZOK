from mozok.db.models import AgentRecord
from mozok.schemas.memory import MemorySearchResult


def build_system_prompt(
    agent: AgentRecord,
    memories: list[MemorySearchResult],
    short_term_block: str | None = None,
) -> str:
    memory_lines = []
    for mem in memories:
        memory_lines.append(
            f"- [{mem.memory_type}, importance={mem.importance}, id={mem.id}] {mem.content}"
        )

    memory_block = "\n".join(memory_lines) if memory_lines else "No relevant long-term memories found."
    recent_block = short_term_block or "No recent short-term conversation."

    return f"""
You are {agent.name}.

Agent ID:
{agent.id}

Description:
{agent.description or "No description."}

Personality:
{agent.personality or "No personality profile."}

Current state:
{agent.state_json or {}}

Core instructions:
{agent.system_prompt or "Use memories when relevant. Do not invent memories."}

Recent conversation / short-term working memory:
{recent_block}

Relevant long-term memories from PostgreSQL + FAISS:
{memory_block}

Answer naturally and stay consistent with your identity, state, recent conversation, and long-term memories.
""".strip()
