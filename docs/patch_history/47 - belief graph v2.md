# 47 - Belief Graph V2

Upgraded conservative belief revision into a small reviewable belief graph layer.

## Added

- Claim-level `source_trust`, `valid_from`, and `valid_until`.
- Candidate-level source trust, temporal status, and suggested confidence delta.
- Belief graph nodes and edges in preview responses.
- Recommended KnowledgeRelation payloads for reviewed graph updates.
- Proposal operations that can create reviewed `supports`, `contradicts`, and `supersedes` graph edges.

## Deferred

This is still deterministic and conservative. It does not automatically rewrite or delete memories.
