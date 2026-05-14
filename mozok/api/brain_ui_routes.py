from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["mozok brain ui"])


def _page(title: str, body: str) -> HTMLResponse:
    html = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 0; background: #10131a; color: #eef2ff; }}
    header {{ padding: 28px 36px; background: linear-gradient(135deg, #232946, #121629); border-bottom: 1px solid #313750; }}
    main {{ padding: 24px 36px 42px; max-width: 1120px; margin: auto; }}
    a {{ color: #8bd3ff; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 16px; }}
    .card {{ background: #171b26; border: 1px solid #2d3348; border-radius: 16px; padding: 18px; box-shadow: 0 12px 24px rgba(0,0,0,.25); }}
    .tag {{ display:inline-block; padding: 4px 9px; border-radius: 999px; background:#26324a; margin: 3px; font-size: 12px; }}
    code, pre {{ background: #0b0e14; color: #d9e2ff; border-radius: 10px; padding: 12px; overflow:auto; }}
    button {{ border: 0; border-radius: 10px; padding: 10px 14px; background: #7f5af0; color: white; cursor: pointer; }}
    input, textarea {{ width:100%; box-sizing:border-box; border-radius:10px; border:1px solid #38405a; background:#0d1018; color:#eef2ff; padding:10px; }}
    textarea {{ min-height: 130px; }}
    .muted {{ color:#b8c1ec; }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p class="muted">Tiny read-only/operator UI for explaining and inspecting the Mozok brain backend.</p>
  </header>
  <main>{body}</main>
</body>
</html>
"""
    return HTMLResponse(html)


@router.get("/ui", response_class=HTMLResponse)
def brain_ui_home() -> HTMLResponse:
    return _page(
        "MOZOK Brain Console",
        """
<div class="grid">
  <section class="card"><h2>Memory</h2><p>Long-term and short-term memory, with summarisation, deduplication, and maintenance.</p><span class="tag">raw</span><span class="tag">episodic</span><span class="tag">semantic</span><span class="tag">core</span></section>
  <section class="card"><h2>Context</h2><p>ContextBuilder assembles the prompt from memories, goals, skills, lore, entity states, and relations.</p><a href="/docs#/default/debug_context_debug_context_post">Open debug context in Swagger</a></section>
  <section class="card"><h2>Scenario Studio</h2><p>Create a brain pack draft without writing raw JSON from scratch.</p><a href="/ui/scenario-studio">Open Scenario Studio</a></section>
  <section class="card"><h2>Knowledge Graph</h2><p>Visualise relations between memories, goals, lore, skills, and entities.</p><a href="/ui/knowledge-graph">Open graph viewer</a></section>
  <section class="card"><h2>Runtime Tick</h2><p>Run an agent step: context → cognitive field → self-model → action plan → proposal.</p><a href="/docs#/agent%20runtime%20tick">Open runtime endpoints</a></section>
  <section class="card"><h2>Change Proposals</h2><p>Learning happens through reviewable proposals instead of silent mutation.</p><a href="/docs#/change%20proposals">Open proposal endpoints</a></section>
</div>
        """,
    )


@router.get("/ui/scenario-studio", response_class=HTMLResponse)
def scenario_studio_ui() -> HTMLResponse:
    body = """
<section class="card">
  <h2>Scenario Studio MVP</h2>
  <p>Paste a friendly scenario draft below and send it to <code>/scenario-studio/build</code>. This page is intentionally tiny; Swagger remains the main editor for now.</p>
  <pre>{
  "world_id": "showcase_old_well",
  "title": "The Old Well Showcase",
  "agents": [{"agent_id": "npc_alice_showcase", "name": "Alice", "role": "npc"}],
  "lorebook_entries": [{"entry_key": "old_well_public", "title": "The Old Well", "content": "Villagers avoid the old well after sunset."}]
}</pre>
  <p><a href="/docs#/scenario%20studio/build_scenario_pack_scenario_studio_build_post">Open build endpoint in Swagger</a></p>
</section>
"""
    return _page("Scenario Studio", body)


@router.get("/ui/knowledge-graph", response_class=HTMLResponse)
def knowledge_graph_ui() -> HTMLResponse:
    body = """
<section class="card">
  <h2>Visual Knowledge Graph MVP</h2>
  <p>Use the endpoint below to fetch graph JSON with nodes and edges that a browser, PyVis, Cytoscape, or game editor can draw.</p>
  <pre>POST /agents/{agent_id}/knowledge-graph/visual
{
  "world_id": "default",
  "limit": 100,
  "include_inactive": false
}</pre>
  <p><a href="/docs#/visual%20knowledge%20graph">Open visual graph endpoints in Swagger</a></p>
</section>
"""
    return _page("Knowledge Graph Viewer", body)
