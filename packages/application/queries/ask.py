"""知识问答查询（B6，设计② AskKnowledgeBase）"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.domain.schemas import AskResponse


def ask_knowledge_base(
    *, question: str, top_k: int = 5, max_rounds: int = 3, on_progress=None
) -> AskResponse:
    """迭代 RAG 问答（多轮检索 + 质量评估）；领域服务自带事务"""
    from packages.ai.rag_service import RAGService

    return RAGService().ask_iterative(
        question=question,
        max_rounds=max_rounds,
        initial_top_k=top_k,
        on_progress=on_progress,
    )


def ask_once(*, question: str, top_k: int = 5) -> AskResponse:
    from packages.ai.rag_service import RAGService

    return RAGService().ask(question, top_k=top_k)
