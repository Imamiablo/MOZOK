from mozok.scenario_import.memory_importer import (
    BrainPackMemoryImporter,
    iter_memory_items,
    normalise_memory_type,
)


class FakeMemoryRecord:
    def __init__(self, id=123):
        self.id = id


class FakeMemoryService:
    def __init__(self):
        self.calls = []

    def add_memory(self, **kwargs):
        self.calls.append(kwargs)
        return FakeMemoryRecord(id=len(self.calls))


def test_normalise_memory_type_aliases():
    assert normalise_memory_type("fact") == "semantic"
    assert normalise_memory_type("event") == "episodic"
    assert normalise_memory_type("message") == "raw"
    assert normalise_memory_type("identity") == "core"
    assert normalise_memory_type("unknown") == "semantic"


def test_iter_memory_items_supports_defaults_and_aliases():
    pack = {
        "defaults": {"agent_id": "npc_alice"},
        "memories": [
            {"text": "Alice knows about the old well.", "type": "fact", "importance": "0.9"},
            {"content": "Alice saw tracks near the tunnels.", "memory_type": "episodic"},
        ],
    }

    items = list(iter_memory_items(pack))

    assert len(items) == 2
    assert items[0].agent_id == "npc_alice"
    assert items[0].content == "Alice knows about the old well."
    assert items[0].memory_type == "semantic"
    assert items[0].importance == 0.9
    assert items[1].memory_type == "episodic"


def test_iter_memory_items_supports_mapping_by_agent():
    pack = {
        "memories": {
            "npc_alice": ["Alice remembers the cellar.", {"content": "Alice trusts Bob.", "type": "preference"}],
            "npc_bob": [{"content": "Bob fears the well.", "type": "fact"}],
        }
    }

    items = list(iter_memory_items(pack))

    assert [item.agent_id for item in items] == ["npc_alice", "npc_alice", "npc_bob"]
    assert [item.memory_type for item in items] == ["semantic", "semantic", "semantic"]


def test_dry_run_previews_without_creating_memories():
    service = FakeMemoryService()
    importer = BrainPackMemoryImporter(db=None, memory_service=service)

    result = importer.import_pack_memories(
        {
            "defaults": {"agent_id": "npc_alice"},
            "memories": [{"content": "Alice knows about the old well."}],
        },
        dry_run=True,
    )

    assert result.seen == 1
    assert result.created == 0
    assert result.preview[0]["agent_id"] == "npc_alice"
    assert service.calls == []


def test_import_creates_memories_through_memory_service():
    service = FakeMemoryService()
    importer = BrainPackMemoryImporter(db=None, memory_service=service)

    result = importer.import_pack_memories(
        {
            "defaults": {"agent_id": "npc_alice"},
            "memories": [
                {
                    "content": "Alice knows about the old well.",
                    "memory_type": "semantic",
                    "metadata": {"lorebook_key": "old_well"},
                }
            ],
        }
    )

    assert result.created == 1
    assert result.created_ids == [1]
    assert service.calls[0]["agent_id"] == "npc_alice"
    assert service.calls[0]["content"] == "Alice knows about the old well."
    assert service.calls[0]["memory_type"] == "semantic"
    assert service.calls[0]["metadata"]["source"] == "brain_pack_import"
    assert service.calls[0]["metadata"]["lorebook_key"] == "old_well"


def test_import_creates_memorycreate_for_current_memory_service_signature():
    class CurrentStyleMemoryService:
        def __init__(self):
            self.calls = []

        def add_memory(self, data):
            self.calls.append(data)
            return FakeMemoryRecord(id=99)

    service = CurrentStyleMemoryService()
    importer = BrainPackMemoryImporter(db=None, memory_service=service)

    result = importer.import_pack_memories(
        {
            "defaults": {"agent_id": "npc_alice"},
            "memories": [{"content": "Alice knows the old well.", "importance": 0.9}],
        }
    )

    assert result.errors == []
    assert result.created == 1
    assert result.created_ids == [99]
    assert service.calls[0].agent_id == "npc_alice"
    assert service.calls[0].content == "Alice knows the old well."
    assert service.calls[0].importance == 9


def test_import_normalises_direct_ten_point_importance_for_memorycreate():
    class CurrentStyleMemoryService:
        def __init__(self):
            self.calls = []

        def add_memory(self, data):
            self.calls.append(data)
            return FakeMemoryRecord(id=100)

    service = CurrentStyleMemoryService()
    importer = BrainPackMemoryImporter(db=None, memory_service=service)

    result = importer.import_pack_memories(
        {
            "defaults": {"agent_id": "npc_alice"},
            "memories": [{"content": "Alice trusts Bob.", "importance": 8}],
        }
    )

    assert result.errors == []
    assert result.created == 1
    assert service.calls[0].importance == 8
