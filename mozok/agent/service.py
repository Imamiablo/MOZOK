from datetime import datetime, timezone
from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord


class AgentService:
    """Service for creating and reading agent profiles.

    Other parts of Mozok should use this service instead of touching
    AgentRecord directly.
    """

    def __init__(self, db: Session):
        self.db = db

    def create_agent(
        self,
        agent_id: str,
        name: str,
        description: str = "",
        personality: str = "",
        system_prompt: str = "",
        state: dict | None = None,
        metadata: dict | None = None,
    ) -> AgentRecord:
        agent = AgentRecord(
            id=agent_id,
            name=name,
            description=description,
            personality=personality,
            system_prompt=system_prompt,
            state_json=state or {},
            metadata_json=metadata or {},
        )

        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        return self.db.get(AgentRecord, agent_id)

    def get_or_create_default_agent(self, agent_id: str) -> AgentRecord:
        agent = self.get_agent(agent_id)
        if agent is not None:
            return agent

        return self.create_agent(
            agent_id=agent_id,
            name=agent_id,
            description="Default Mozok agent.",
            personality="Helpful, curious, and remembers relevant past events.",
            system_prompt="Use memories when relevant. Do not invent memories.",
            state={},
            metadata={},
        )

    def update_state(self, agent_id: str, state_update: dict) -> AgentRecord:
        agent = self.get_or_create_default_agent(agent_id)
        current_state = dict(agent.state_json or {})
        current_state.update(state_update)

        agent.state_json = current_state
        agent.updated_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(agent)
        return agent


