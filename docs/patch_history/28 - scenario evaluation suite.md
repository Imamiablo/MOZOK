# 28 - Scenario evaluation suite

## Summary

Added a reusable scenario-context regression suite for MOZOK.

The goal is to test whole scenario behaviour, not only isolated service methods:

1. Import a brain/scenario pack.
2. Import indexed memories through `MemoryService`.
3. Build a real `ContextBuilder` package for an agent turn.
4. Assert that expected context is present.
5. Assert that hidden/restricted/narrator-only context does not leak.

## Added

- `mozok/scenario_evaluation/__init__.py`
- `mozok/scenario_evaluation/runner.py`
- `tests/fixtures/brain_packs/scenario_evaluation_pack.json`
- `tests/scenario/test_scenario_evaluation_suite.py`

## Scenario runner capabilities

The new `ScenarioContextExpectations` supports checks for:

- required prompt text
- forbidden prompt text
- required memory text
- forbidden memory text
- required/forbidden lorebook keys
- required/forbidden goal keys
- required/forbidden procedural skill keys
- required/forbidden entity IDs
- minimum counts for memories, goals, procedural skills, knowledge relations, lorebook entries, entity states, and short-term memory

## Covered scenario behaviours

The scenario fixture now verifies that:

- Alice receives public lore, her restricted known lore, her active secrecy goal, her relevant procedural skill, her entity-state view of Bob, related knowledge relations, and her imported semantic memory.
- Alice does not receive narrator-only lore.
- Bob receives public lore and Bob's own memory.
- Bob does not receive Alice's restricted lore, Alice's entity-state view, Alice's goal, or Alice's memory.
- The runner reports failure when forbidden context is present.
- Debug output still exposes the expected pipeline steps.

## Tests

Full test command:

```bash
python -m pytest -q
```

Result in the review environment:

```text
125 passed, 3 skipped, 7 warnings
```

The skipped tests are HTTP smoke tests that require a running local MOZOK API.
