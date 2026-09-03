"""Per-tender pipeline：explicit LangGraph StateGraph（verify → digest）。

取代舊有「三個獨立 tool（verify/download/digest），由 LLM 決定順序」嘅做法。
而家 process_tender 一次過跑 verify → digest；digest 係 agentic node，
可以 call search_web / read_page 補官方資料再寫 01_digest.md。
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from .. import nodes


class PipelineState(TypedDict, total=False):
    tender_id: str
    tender: dict
    status: str
    dossier_dir: str
    issuer: str
    tender_no: str
    deadline: str
    official_url: str
    doc_links: list[str]
    source_md: str
    digest_md: str
    candidates_md: str
    logs: Annotated[list[dict], operator.add]
    error: str


def _build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("verify", nodes.verify_node)
    graph.add_node("digest", nodes.digest_node)
    graph.add_node("candidates", nodes.candidates_node)
    graph.add_edge(START, "verify")
    graph.add_edge("verify", "digest")
    graph.add_edge("digest", "candidates")
    graph.add_edge("candidates", END)
    return graph.compile()


_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = _build_graph()
    return _pipeline
