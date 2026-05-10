from __future__ import annotations

import json
from pathlib import Path

import pytest

from mozok.scenario_import.brain_pack_file_loader import (
    BrainPackNameError,
    BrainPackNotFoundError,
    candidate_brain_pack_paths,
    find_brain_pack_file,
    load_brain_pack_by_name,
    normalise_brain_pack_name,
)


def test_accepts_simple_name_without_extension():
    assert normalise_brain_pack_name("cyberpunk_demo_brain_pack") == "cyberpunk_demo_brain_pack"


def test_accepts_allowed_extension():
    assert normalise_brain_pack_name("cyberpunk_demo_brain_pack.json") == "cyberpunk_demo_brain_pack.json"


def test_rejects_unsafe_paths():
    for value in ["../evil", "nested/pack", r"nested\\pack", "C:/Users/me/pack", ".env", "pack:evil"]:
        with pytest.raises(BrainPackNameError):
            normalise_brain_pack_name(value)


def test_candidate_paths_try_json_yaml_yml(tmp_path: Path):
    candidates = candidate_brain_pack_paths("demo", base_dir=tmp_path)
    assert candidates == [tmp_path / "demo.json", tmp_path / "demo.yaml", tmp_path / "demo.yml"]


def test_finds_json_by_name_without_extension(tmp_path: Path):
    path = tmp_path / "demo.json"
    path.write_text(json.dumps({"schema_version": 1, "agents": []}), encoding="utf-8")

    assert find_brain_pack_file("demo", base_dir=tmp_path) == path


def test_loads_json_by_name_and_returns_path(tmp_path: Path):
    path = tmp_path / "demo.json"
    path.write_text(json.dumps({"schema_version": 1, "world_id": "test_world"}), encoding="utf-8")

    pack, loaded_from = load_brain_pack_by_name("demo", base_dir=tmp_path)

    assert loaded_from == path
    assert pack["world_id"] == "test_world"


def test_clear_not_found_error(tmp_path: Path):
    with pytest.raises(BrainPackNotFoundError) as exc_info:
        find_brain_pack_file("missing_pack", base_dir=tmp_path)

    message = str(exc_info.value)
    assert "missing_pack" in message
    assert "missing_pack.json" in message
