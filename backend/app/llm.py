"""DeepSeek LLM（OpenAI-compatible），經 langchain-openai 嘅 ChatOpenAI 接。"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from . import config


def build_model() -> ChatOpenAI:
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY（放 backend/.env）")
    return ChatOpenAI(
        model=config.DEEPSEEK_MODEL,
        base_url=config.DEEPSEEK_BASE_URL,
        api_key=config.DEEPSEEK_API_KEY,
        temperature=0,
        timeout=120,
        max_retries=1,
    )
