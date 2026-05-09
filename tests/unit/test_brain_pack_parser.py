from __future__ import annotations

from mozok.scenario_import.service import parse_lorebook_markdown_text, slugify


def test_slugify_makes_stable_keys():
    assert slugify("The Old Well!") == "the_old_well"
    assert slugify("  Bobozavrik  ") == "bobozavrik"


def test_parse_legacy_markdown_lorebook_text():
    text = """
# WORLD LORE
# This is a comment.

## ANIMALS

### Bobozavrik
Lives in the mountains, feeds on beans and humans.
Very friendly to those who give it beans.

### Werewolf
A nocturnal animal similar to a wolf.

## PLANTS

### Dragon Leaf
Poisonous leaves from dark forests.
"""

    entries = parse_lorebook_markdown_text(
        text,
        world_id="example_world",
        visibility="narrator_only",
        importance=6,
        source_name="example.txt",
    )

    assert len(entries) == 3
    assert entries[0]["entry_key"] == "bobozavrik"
    assert entries[0]["category"] == "animal"
    assert entries[0]["visibility"] == "narrator_only"
    assert entries[0]["importance"] == 6
    assert "beans and humans" in entries[0]["content"]
    assert entries[2]["entry_key"] == "dragon_leaf"
    assert entries[2]["category"] == "plant"
