# Patch 21 — Procedural Skills V2: relevance selection

## Goal

Make Procedural Skills useful when agents have many active skills.

V1 included active skills by priority/limit. V2 can deterministically select relevant skills based on:

- trigger keywords in the current user message;
- active goal keys already selected for context;
- selected lorebook entry keys;
- selected entity-state entity IDs;
- fallback to top-priority skills when nothing matches.

## Added

- `ProceduralSkillService.select_relevant_skills(...)`
- `GET /agents/{agent_id}/procedural-skills/select`
- `select_relevant_procedural_skills` option for `/debug/context` and `/chat`
- `procedural_skill_selection` debug metadata in context/chat responses
- tests for keyword matching, goal matching, fallback selection, and the select endpoint

## Intent

This is deterministic and does not call an LLM or embeddings. It is meant to be easy to debug before adding more advanced skill selection later.
