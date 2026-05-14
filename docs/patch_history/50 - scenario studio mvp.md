# 50 - Scenario Studio MVP

Added a draft-to-brain-pack helper for building scenarios without hand-writing full JSON.

## Added

- `mozok/scenario_studio/schemas.py`
- `mozok/scenario_studio/service.py`
- `POST /scenario-studio/build`
- `POST /scenario-studio/save`

## Features

- Builds importable brain pack JSON from friendly agent/lore/goal/skill/entity/memory drafts.
- Auto-links goals to lore and skills to goals through knowledge relations.
- Can emit a small evaluation-pack smoke-test stub.
- Can save generated packs under `data/brain_packs`.
