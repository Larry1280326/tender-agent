"""Draw the backend LangGraph graphs as Mermaid PNGs (and .mmd source), with tools.

Usage:
    python draw_graph.py            # from backend/ (or .venv/Scripts/python.exe draw_graph.py)

Produces, in backend/:
    agent_graph.png / .mmd         — main chatbot ReAct agent (8 tools)
    pipeline_graph.png / .mmd      — per-tender verify -> digest -> candidates StateGraph
    digest_agent_graph.png / .mmd  — digest sub-agent (search_web / read_page)
    candidates_agent_graph.png/.mmd — candidates sub-agent (search_web / read_page)

The diagrams annotate the tools each node can use: the ReAct `tools` node
(ToolNode) dispatches to its bound tools, and the pipeline nodes annotate the
services / sub-agent they call.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from langchain_core.runnables.graph_mermaid import draw_mermaid_png

BACKEND_ROOT = Path(__file__).resolve().parent

# Ensure we can import the `app` package regardless of CWD.
sys.path.insert(0, str(BACKEND_ROOT))

_FRONTMATTER = (
    "---\n"
    "config:\n"
    "  flowchart:\n"
    "    curve: linear\n"
    "---\n"
)


def _render(name: str, mermaid_src: str, out_dir: Path) -> None:
    (out_dir / f"{name}.mmd").write_text(mermaid_src, encoding="utf-8")
    png_path = out_dir / f"{name}.png"
    try:
        draw_mermaid_png(mermaid_src, output_file_path=str(png_path))
        print(f"[ok] {name}.png + .mmd written")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {name}.png failed: {e}")
        print(f"       (mermaid source saved to {name}.mmd; render it at https://mermaid.live)")


def _react_agent_mermaid(title: str, model: str, tools: list[str]) -> str:
    """ReAct agent: __start__ -> agent <-> tools -> __end__, tools dispatch to bound tools."""
    lines = [
        _FRONTMATTER,
        "graph TD;",
        "\t__start__([__start__]) --> agent",
        f'\tagent["{title}<br/><small>LLM · {model}</small>"] -->|tool call| tools',
        '\ttools["tools · ToolNode"] --> agent',
        '\tagent -.->|done| __end__([__end__])',
    ]
    for t in tools:
        label = t
        if t == "send_email":
            label = "send_email 🔒"  # human-in-the-loop interrupt
        lines.append(f"\ttools -.-> t_{t}[{label}]")
    return "\n".join(lines) + "\n"


def _pipeline_mermaid() -> str:
    """Per-tender pipeline: verify -> digest -> candidates, with services/sub-agents each node calls."""
    return "\n".join([
        _FRONTMATTER,
        "graph TD;",
        "\t__start__([__start__]) --> verify",
        "\tverify --> digest",
        "\tdigest --> candidates",
        "\tcandidates --> __end__([__end__])",
        "",
        "\t%% verify node: fetch + cross-check via services (not LangChain tools)",
        '\tverify["verify"] -.-> v1["reader.read · Jina<br/><small>Conneciz detail + official pages</small>"]',
        '\tverify -.-> v2["serper.search · Serper"]',
        '\tverify -.-> v3["LLM · queries / pick pages / judge"]',
        "",
        "\t%% digest node: spins up an agentic sub-agent",
        '\tdigest["digest"] -.-> d1["digest sub-agent"]',
        '\td1 -.-> d2["search_web"]',
        '\td1 -.-> d3["read_page"]',
        "",
        "\t%% candidates node: spins up an agentic sub-agent",
        '\tcandidates["candidates"] -.-> c1["candidates sub-agent"]',
        '\tc1 -.-> c2["search_web"]',
        '\tc1 -.-> c3["read_page"]',
    ]) + "\n"


async def main() -> None:
    out_dir = BACKEND_ROOT
    out_dir.mkdir(parents=True, exist_ok=True)

    from app import config
    from app.agent.agent import init_agent, get_agent, shutdown_agent
    from app.agent.pipeline import get_pipeline
    from app.agent.tools import ALL_TOOLS
    from app.agent.web_tools import read_page, search_web
    from app import nodes

    await init_agent()
    try:
        # Sanity-check the graph structures we're drawing (keep the diagram honest).
        assert get_agent().get_graph() is not None
        assert get_pipeline().get_graph() is not None

        _render(
            "agent_graph",
            _react_agent_mermaid(
                "agent", config.DEEPSEEK_MODEL, [t.name for t in ALL_TOOLS]
            ),
            out_dir,
        )
        _render(
            "digest_agent_graph",
            _react_agent_mermaid(
                "digest sub-agent",
                config.DEEPSEEK_MODEL,
                [t.name for t in (search_web, read_page)],
            ),
            out_dir,
        )
        _render(
            "candidates_agent_graph",
            _react_agent_mermaid(
                "candidates sub-agent",
                config.DEEPSEEK_MODEL,
                [t.name for t in (search_web, read_page)],
            ),
            out_dir,
        )
        _render("pipeline_graph", _pipeline_mermaid(), out_dir)
    finally:
        await shutdown_agent()


if __name__ == "__main__":
    asyncio.run(main())
