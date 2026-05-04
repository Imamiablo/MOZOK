from mozok.memory.short_term_memory import ShortTermMemoryStore


def test_short_term_memory_is_isolated_by_agent_and_session():
    store = ShortTermMemoryStore(max_messages_per_session=10)

    store.add_message("agent_a", "session_1", "user", "pineapple")
    store.add_message("agent_a", "session_2", "user", "banana")
    store.add_message("agent_b", "session_1", "user", "mango")

    assert [m.content for m in store.get_messages("agent_a", "session_1", 10)] == ["pineapple"]
    assert [m.content for m in store.get_messages("agent_a", "session_2", 10)] == ["banana"]
    assert [m.content for m in store.get_messages("agent_b", "session_1", 10)] == ["mango"]


def test_short_term_memory_clear_session_does_not_clear_other_sessions():
    store = ShortTermMemoryStore(max_messages_per_session=10)

    store.add_message("agent_a", "session_1", "user", "first")
    store.add_message("agent_a", "session_2", "user", "second")

    removed = store.clear_session("agent_a", "session_1")

    assert removed == 1
    assert store.get_messages("agent_a", "session_1", 10) == []
    assert [m.content for m in store.get_messages("agent_a", "session_2", 10)] == ["second"]


def test_short_term_memory_respects_limit_and_keeps_recent_messages():
    store = ShortTermMemoryStore(max_messages_per_session=5)

    for index in range(8):
        store.add_message("agent_a", "session_1", "user", f"message {index}")

    recent = store.get_messages("agent_a", "session_1", limit=3)

    assert [m.content for m in recent] == ["message 5", "message 6", "message 7"]
