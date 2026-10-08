"""E3：Terminal 确定性命令的 Python 侧 capability adapter 骨架

C4 注册表定义了 capability → handler 映射；本模块是 HTTP application 调用的
薄适配层——Terminal 的确定性子命令（pm papers search、pm claims list 等）
经此调用 application 层，返回 canonical result（JSON-able dict）。

C4 注册表 + 本适配器 = Terminal 子命令的完整后端。
Python Executor（C7）走同一 adapter（协议路径）；Pi downstream（E1）经
capability metadata 派生 TS 侧调用。

每个 adapter 函数接收 `session` + `**params`，返回 plain dict。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def search_papers(session: Session, *, query: str, limit: int = 10) -> dict:
    from packages.application.queries.papers import search_papers as _search

    return _search(session, keyword=query, limit=limit)


def get_paper(session: Session, *, paper_id: str) -> dict:
    from packages.application.queries.papers import get_paper

    return get_paper(session, paper_id)


def get_research_question(session: Session, *, question_id: str) -> dict:
    from packages.application.queries.research_state import get_research_question

    return get_research_question(session, question_id)


def list_claims(session: Session, *, question_id: str, statuses: list[str] | None = None) -> dict:
    from packages.application.queries.research_state import list_claims

    return list_claims(session, question_id, statuses=statuses)


def get_claim_evidence(session: Session, *, claim_id: str) -> dict:
    from packages.application.queries.research_state import get_claim_evidence

    return get_claim_evidence(session, claim_id)


def diff_research_state(session: Session, *, question_id: str) -> dict:
    from packages.application.queries.research_state import diff_research_state

    return diff_research_state(session, question_id)


def export_research_object(session: Session, *, question_id: str) -> dict:
    from packages.application.queries.research_export import export_research_object

    return export_research_object(session, question_id)
