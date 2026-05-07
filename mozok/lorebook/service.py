"""
Service layer for Lorebook.
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from mozok.lorebook.models import AgentLorebookKnowledgeRecord, LorebookEntryRecord
from mozok.lorebook.schemas import (
    AgentLorebookKnowledgeUpsert,
    LorebookContextItem,
    LorebookEntryUpsert,
)


class LorebookService:
    """Database operations for lorebook entries and agent knowledge links."""

    def __init__(self, db: Session):
        self.db = db

    def upsert_entry(self, data: LorebookEntryUpsert) -> LorebookEntryRecord:
        entry = (
            self.db.query(LorebookEntryRecord)
            .filter(
                LorebookEntryRecord.world_id == data.world_id,
                LorebookEntryRecord.entry_key == data.entry_key,
            )
            .one_or_none()
        )

        if entry is None:
            entry = LorebookEntryRecord(
                world_id=data.world_id,
                entry_key=data.entry_key,
                title=data.title,
                content=data.content,
                category=data.category,
                visibility=data.visibility,
                importance=data.importance,
                tags=data.tags,
                entry_metadata=data.metadata,
            )
            self.db.add(entry)
        else:
            entry.title = data.title
            entry.content = data.content
            entry.category = data.category
            entry.visibility = data.visibility
            entry.importance = data.importance
            entry.tags = data.tags
            entry.entry_metadata = data.metadata
            entry.is_active = True

        self.db.commit()
        self.db.refresh(entry)
        return entry

    def list_entries(self, world_id: str = "default", include_inactive: bool = False) -> list[LorebookEntryRecord]:
        query = self.db.query(LorebookEntryRecord).filter(LorebookEntryRecord.world_id == world_id)
        if not include_inactive:
            query = query.filter(LorebookEntryRecord.is_active.is_(True))
        return query.order_by(LorebookEntryRecord.importance.desc(), LorebookEntryRecord.id.asc()).all()

    def upsert_agent_knowledge(self, data: AgentLorebookKnowledgeUpsert) -> AgentLorebookKnowledgeRecord:
        entry = (
            self.db.query(LorebookEntryRecord)
            .filter(
                LorebookEntryRecord.world_id == data.world_id,
                LorebookEntryRecord.entry_key == data.entry_key,
                LorebookEntryRecord.is_active.is_(True),
            )
            .one_or_none()
        )
        if entry is None:
            raise ValueError(f"Lorebook entry not found: world_id={data.world_id!r}, entry_key={data.entry_key!r}")

        link = (
            self.db.query(AgentLorebookKnowledgeRecord)
            .filter(
                AgentLorebookKnowledgeRecord.agent_id == data.agent_id,
                AgentLorebookKnowledgeRecord.lorebook_entry_id == entry.id,
            )
            .one_or_none()
        )

        if link is None:
            link = AgentLorebookKnowledgeRecord(
                agent_id=data.agent_id,
                lorebook_entry_id=entry.id,
                knowledge_state=data.knowledge_state,
                confidence=data.confidence,
                notes=data.notes,
                knowledge_metadata=data.metadata,
            )
            self.db.add(link)
        else:
            link.knowledge_state = data.knowledge_state
            link.confidence = data.confidence
            link.notes = data.notes
            link.knowledge_metadata = data.metadata
            link.is_active = True

        self.db.commit()
        self.db.refresh(link)
        return link

    def build_agent_lorebook_context(
        self,
        agent_id: str,
        world_id: str = "default",
        limit: int = 10,
        include_public: bool = True,
        include_narrator_only: bool = False,
    ) -> list[LorebookContextItem]:
        explicit_links = (
            self.db.query(AgentLorebookKnowledgeRecord)
            .options(joinedload(AgentLorebookKnowledgeRecord.entry))
            .join(LorebookEntryRecord)
            .filter(
                AgentLorebookKnowledgeRecord.agent_id == agent_id,
                AgentLorebookKnowledgeRecord.is_active.is_(True),
                LorebookEntryRecord.world_id == world_id,
                LorebookEntryRecord.is_active.is_(True),
            )
            .all()
        )

        items_by_entry_id: dict[int, LorebookContextItem] = {}

        for link in explicit_links:
            entry = link.entry
            if link.knowledge_state == "hidden":
                continue

            items_by_entry_id[entry.id] = LorebookContextItem(
                lorebook_entry_id=entry.id,
                world_id=entry.world_id,
                entry_key=entry.entry_key,
                title=entry.title,
                category=entry.category,
                visibility=entry.visibility,
                importance=entry.importance,
                knowledge_state=link.knowledge_state,
                confidence=link.confidence,
                content=entry.content,
                tags=entry.tags or [],
                metadata={
                    **(entry.entry_metadata or {}),
                    "agent_knowledge_notes": link.notes,
                    "agent_knowledge_metadata": link.knowledge_metadata or {},
                },
            )

        visibility_filters = []
        if include_public:
            visibility_filters.append(LorebookEntryRecord.visibility == "public")
        if include_narrator_only:
            visibility_filters.append(LorebookEntryRecord.visibility == "narrator_only")

        if visibility_filters:
            public_entries = (
                self.db.query(LorebookEntryRecord)
                .filter(
                    LorebookEntryRecord.world_id == world_id,
                    LorebookEntryRecord.is_active.is_(True),
                    or_(*visibility_filters),
                )
                .all()
            )

            hidden_entry_ids = {
                link.lorebook_entry_id
                for link in explicit_links
                if link.knowledge_state == "hidden"
            }

            for entry in public_entries:
                if entry.id in hidden_entry_ids or entry.id in items_by_entry_id:
                    continue

                items_by_entry_id[entry.id] = LorebookContextItem(
                    lorebook_entry_id=entry.id,
                    world_id=entry.world_id,
                    entry_key=entry.entry_key,
                    title=entry.title,
                    category=entry.category,
                    visibility=entry.visibility,
                    importance=entry.importance,
                    knowledge_state="public" if entry.visibility == "public" else "narrator_visible",
                    confidence=None,
                    content=entry.content,
                    tags=entry.tags or [],
                    metadata=entry.entry_metadata or {},
                )

        items = list(items_by_entry_id.values())
        items.sort(key=lambda item: (-item.importance, item.title.lower(), item.lorebook_entry_id))
        return items[:limit]


def format_lorebook_context(items: list[LorebookContextItem]) -> str:
    """Format lorebook items for prompt injection/debug display."""
    if not items:
        return "No lorebook entries available for this agent."

    lines = ["Lorebook / world knowledge available to this agent:"]
    for item in items:
        confidence = f", confidence={item.confidence}/10" if item.confidence is not None else ""
        lines.append(
            f"- [{item.category}] {item.title} "
            f"(key={item.entry_key}, state={item.knowledge_state}{confidence}): {item.content}"
        )
    return "\n".join(lines)
