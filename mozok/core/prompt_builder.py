from mozok.schemas.memory import MemorySearchResult


def build_system_prompt(agent_id: str, memories: list[MemorySearchResult]) -> str:
    """Build a compact prompt from retrieved memories.

    Later this can include identity, mood, goals, allowed actions, etc.
    """

    memory_lines = []
    for mem in memories:
        memory_lines.append(
            f"- [{mem.memory_type}, importance={mem.importance}, id={mem.id}] {mem.content}"
        )

    memory_block = "\n".join(memory_lines) if memory_lines else "No relevant memories found."

    return f"""
You are Mozok agent '{agent_id}'.

You are a reusable bot-brain core.
Use memories when they are relevant, but do not pretend that memories say things they do not say.

Relevant memories:
{memory_block}

Answer naturally and briefly.
""".strip()
