from mozok.core.bot_core import get_memory_service
from mozok.db.session import SessionLocal
from mozok.schemas.memory import MemoryCreate


def main():
    db = SessionLocal()
    try:
        memory = get_memory_service(db)
        examples = [
            "Denys wants a reusable bot brain that can connect to games and chat bots.",
            "Mozok should use PostgreSQL as source of truth and FAISS as fast semantic index.",
            "The bot should remember events, relationships, plans, and preferences.",
        ]
        for text in examples:
            record = memory.add_memory(
                MemoryCreate(
                    agent_id="demo_agent",
                    content=text,
                    memory_type="fact",
                    importance=7,
                )
            )
            print(f"Added memory {record.id}: {text}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
