from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from mozok.db.models import WorldEventRecord
from mozok.perception.schemas import PerceptionEvent
from mozok.world_events.schemas import (
    WorldEventAcknowledgeRequest,
    WorldEventAcknowledgeResponse,
    WorldEventConsumeRequest,
    WorldEventConsumeResponse,
    WorldEventCreate,
    WorldEventCreateRequest,
    WorldEventCreateResponse,
    WorldEventExpireRequest,
    WorldEventExpireResponse,
    WorldEventRead,
    WorldEventSearchRequest,
    WorldEventSearchResponse,
    WorldEventToPerceptionRequest,
    WorldEventToPerceptionResponse,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: str | None, fallback: str = "default") -> str:
    clean = " ".join(str(value or "").strip().split())
    return clean or fallback


def _append_unique(values: Iterable[str] | None, value: str) -> list[str]:
    result = [str(item) for item in values or [] if str(item)]
    if value not in result:
        result.append(value)
    return result


class WorldEventService:
    """SQL-backed World Event Bus V2.

    Events are durable records with consume/ack/TTL history. External game/app
    adapters still own real world mutation; Mozok only records and compiles
    events into perception inputs for cognition/runtime ticks.
    """

    def __init__(self, db: Session):
        self.db = db

    def create(self, request: WorldEventCreateRequest) -> WorldEventCreateResponse:
        now = utc_now()
        events: list[WorldEventRead] = []
        for item in request.events:
            event_id = f"evt_{uuid4().hex[:16]}"
            expires_at = now + timedelta(seconds=item.ttl_seconds) if item.ttl_seconds else None
            read = WorldEventRead(
                event_id=event_id,
                world_id=item.world_id,
                agent_id=item.agent_id,
                event_type=item.event_type,
                content=item.content,
                source=item.source,
                channel_hint=item.channel_hint,
                salience=item.salience,
                reliability=item.reliability,
                visibility=item.visibility,
                tags=list(item.tags),
                metadata=dict(item.metadata),
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
                active=True,
            )
            events.append(read)
            if request.store:
                self.db.add(self._record_from_create(item, event_id=event_id, now=now, expires_at=expires_at))
        if request.store:
            self.db.commit()
        return WorldEventCreateResponse(
            read_only=not request.store,
            stored=bool(request.store),
            event_count=len(events),
            events=events,
            notes=[
                "World Event Bus V2 stores events in the world_events SQL table.",
                "Use consume/ack endpoints to track which agents processed events.",
            ],
        )

    def search(self, request: WorldEventSearchRequest) -> WorldEventSearchResponse:
        events = self._search_records(request)
        return WorldEventSearchResponse(world_id=request.world_id, event_count=len(events), events=[self._to_read(record) for record in events])

    def consume(self, request: WorldEventConsumeRequest) -> WorldEventConsumeResponse:
        if not request.agent_id:
            return WorldEventConsumeResponse(world_id=request.world_id, agent_id="", notes=["agent_id is required to consume events."])
        records = self._search_records(request)
        if request.mark_consumed:
            now = utc_now()
            for record in records:
                record.consumed_by_agent_ids_json = _append_unique(record.consumed_by_agent_ids_json, request.agent_id)
                metadata = dict(record.metadata_json or {})
                consumed_at = dict(metadata.get("consumed_at_by_agent") or {})
                consumed_at[request.agent_id] = now.isoformat()
                metadata["consumed_at_by_agent"] = consumed_at
                record.metadata_json = metadata
                record.updated_at = now
                self.db.add(record)
            self.db.commit()
        return WorldEventConsumeResponse(
            world_id=request.world_id,
            agent_id=request.agent_id,
            consumed_count=len(records),
            events=[self._to_read(record) for record in records],
            notes=["Events were marked as consumed for this agent." if request.mark_consumed else "Read-only consume preview."],
        )

    def acknowledge(self, request: WorldEventAcknowledgeRequest) -> WorldEventAcknowledgeResponse:
        query = self.db.query(WorldEventRecord).filter(WorldEventRecord.world_id == _clean(request.world_id))
        if request.event_ids:
            query = query.filter(WorldEventRecord.event_id.in_(request.event_ids))
        records = query.all()
        now = utc_now()
        for record in records:
            if request.acknowledge:
                record.acknowledged_by_agent_ids_json = _append_unique(record.acknowledged_by_agent_ids_json, request.agent_id)
            else:
                record.acknowledged_by_agent_ids_json = [item for item in record.acknowledged_by_agent_ids_json or [] if item != request.agent_id]
            record.updated_at = now
            self.db.add(record)
        self.db.commit()
        return WorldEventAcknowledgeResponse(
            world_id=request.world_id,
            agent_id=request.agent_id,
            acknowledged_count=len(records),
            events=[self._to_read(record) for record in records],
        )

    def expire(self, request: WorldEventExpireRequest) -> WorldEventExpireResponse:
        query = self.db.query(WorldEventRecord)
        if request.world_id:
            query = query.filter(WorldEventRecord.world_id == _clean(request.world_id))
        if request.event_ids:
            query = query.filter(WorldEventRecord.event_id.in_(request.event_ids))
        elif request.expire_before_now:
            now = utc_now()
            query = query.filter(WorldEventRecord.expires_at.isnot(None), WorldEventRecord.expires_at <= now)
        records = query.all()
        expired_ids: list[str] = []
        now = utc_now()
        for record in records:
            if record.active:
                record.active = False
                record.updated_at = now
                self.db.add(record)
                expired_ids.append(record.event_id)
        self.db.commit()
        return WorldEventExpireResponse(expired_count=len(expired_ids), event_ids=expired_ids)

    def to_perception_events(self, request: WorldEventToPerceptionRequest) -> WorldEventToPerceptionResponse:
        found = self.search(request).events
        perception_events = [
            PerceptionEvent(
                content=event.content,
                event_type=event.event_type,
                source=event.source,
                channel_hint=event.channel_hint,
                salience=event.salience,
                reliability=event.reliability,
                tags=list(event.tags),
                metadata={
                    **event.metadata,
                    "world_event_id": event.event_id,
                    "world_id": event.world_id,
                    "consumed_by_agent_ids": event.consumed_by_agent_ids,
                    "acknowledged_by_agent_ids": event.acknowledged_by_agent_ids,
                },
            )
            for event in found
        ]
        return WorldEventToPerceptionResponse(events=found, perception_events=perception_events)

    def _record_from_create(self, item: WorldEventCreate, event_id: str, now: datetime, expires_at: datetime | None) -> WorldEventRecord:
        return WorldEventRecord(
            event_id=event_id,
            world_id=_clean(item.world_id),
            agent_id=item.agent_id,
            event_type=_clean(item.event_type, "world_event"),
            content=item.content,
            source=_clean(item.source, "external"),
            channel_hint=item.channel_hint,
            salience=float(item.salience),
            reliability=float(item.reliability),
            visibility=_clean(item.visibility, "local"),
            tags_json=list(item.tags or []),
            metadata_json=dict(item.metadata or {}),
            consumed_by_agent_ids_json=[],
            acknowledged_by_agent_ids_json=[],
            active=True,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

    def _search_records(self, request: WorldEventSearchRequest) -> list[WorldEventRecord]:
        now = utc_now()
        query = self.db.query(WorldEventRecord).filter(WorldEventRecord.world_id == _clean(request.world_id))
        if not request.include_inactive:
            query = query.filter(WorldEventRecord.active == True)  # noqa: E712
            query = query.filter(or_(WorldEventRecord.expires_at.is_(None), WorldEventRecord.expires_at > now))
        if request.agent_id:
            query = query.filter(
                or_(
                    WorldEventRecord.agent_id.is_(None),
                    WorldEventRecord.agent_id == request.agent_id,
                    WorldEventRecord.visibility == "world",
                )
            )
        if request.event_type:
            query = query.filter(WorldEventRecord.event_type == _clean(request.event_type, "world_event"))
        records = query.order_by(WorldEventRecord.created_at.desc()).limit(max(1, min(int(request.limit), 250))).all()
        if request.tags_any:
            wanted = {tag.lower() for tag in request.tags_any}
            records = [record for record in records if wanted.intersection({str(tag).lower() for tag in record.tags_json or []})]
        if request.agent_id and not request.include_consumed:
            records = [record for record in records if request.agent_id not in set(record.consumed_by_agent_ids_json or [])]
        return records[: request.limit]

    def _to_read(self, record: WorldEventRecord) -> WorldEventRead:
        return WorldEventRead(
            event_id=record.event_id,
            world_id=record.world_id,
            agent_id=record.agent_id,
            event_type=record.event_type,
            content=record.content,
            source=record.source,
            channel_hint=record.channel_hint,
            salience=float(record.salience or 0.0),
            reliability=float(record.reliability or 0.0),
            visibility=record.visibility,
            tags=list(record.tags_json or []),
            metadata=dict(record.metadata_json or {}),
            consumed_by_agent_ids=list(record.consumed_by_agent_ids_json or []),
            acknowledged_by_agent_ids=list(record.acknowledged_by_agent_ids_json or []),
            created_at=record.created_at,
            updated_at=record.updated_at,
            expires_at=record.expires_at,
            active=bool(record.active),
        )
