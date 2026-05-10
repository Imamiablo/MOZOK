from __future__ import annotations

from mozok.scenario_import.service_memory_integration import install_memory_import_integration


class FakeMemoryRecord:
    def __init__(self, id):
        self.id = id


class FakeMemoryService:
    def __init__(self):
        self.calls = []

    def add_memory(self, **kwargs):
        self.calls.append(kwargs)
        return FakeMemoryRecord(id=len(self.calls))


def test_integration_imports_memories_after_main_import():
    fake_memory_service = FakeMemoryService()

    class FakeScenarioImportService:
        def __init__(self):
            self.db = object()
            self.memory_service = fake_memory_service

        def import_pack(self, pack, *, dry_run=False):
            return {"ok": True, "dry_run": dry_run}

    assert install_memory_import_integration(FakeScenarioImportService) is True

    service = FakeScenarioImportService()
    result = service.import_pack(
        {
            "defaults": {"agent_id": "npc_alice"},
            "memories": [
                {
                    "content": "Alice knows the old well connects to the tunnels.",
                    "memory_type": "semantic",
                }
            ],
        }
    )

    assert result["ok"] is True
    assert result["memory_import"]["created"] == 1
    assert result["memory_import"]["seen"] == 1
    assert fake_memory_service.calls[0]["agent_id"] == "npc_alice"
    assert fake_memory_service.calls[0]["content"] == "Alice knows the old well connects to the tunnels."
    assert fake_memory_service.calls[0]["metadata"]["source"] == "scenario_import"


def test_integration_respects_dry_run_and_does_not_create():
    fake_memory_service = FakeMemoryService()

    class FakeScenarioImportService:
        def __init__(self):
            self.memory_service = fake_memory_service

        def import_pack(self, pack, *, dry_run=False):
            return {"ok": True, "dry_run": dry_run}

    assert install_memory_import_integration(FakeScenarioImportService) is True

    service = FakeScenarioImportService()
    result = service.import_pack(
        {
            "defaults": {"agent_id": "npc_alice"},
            "memories": [{"content": "Alice remembers the cellar."}],
        },
        dry_run=True,
    )

    assert result["memory_import"]["dry_run"] is True
    assert result["memory_import"]["seen"] == 1
    assert result["memory_import"]["created"] == 0
    assert fake_memory_service.calls == []


def test_integration_is_idempotent():
    class FakeScenarioImportService:
        def import_pack(self, pack, *, dry_run=False):
            return {"ok": True}

    assert install_memory_import_integration(FakeScenarioImportService) is True
    wrapped_once = FakeScenarioImportService.import_pack

    assert install_memory_import_integration(FakeScenarioImportService) is True
    wrapped_twice = FakeScenarioImportService.import_pack

    assert wrapped_once is wrapped_twice


def test_integration_ignores_packs_without_memories():
    fake_memory_service = FakeMemoryService()

    class FakeScenarioImportService:
        def __init__(self):
            self.memory_service = fake_memory_service

        def import_pack(self, pack, *, dry_run=False):
            return {"ok": True}

    assert install_memory_import_integration(FakeScenarioImportService) is True

    result = FakeScenarioImportService().import_pack({"agents": []})

    assert result == {"ok": True}
    assert fake_memory_service.calls == []
