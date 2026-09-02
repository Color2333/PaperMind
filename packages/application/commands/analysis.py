"""论文分析命令（B8 边界修正，自 queries/analysis 移入）

ReasoningService/FigureService 均产生 LLM 成本、写 PromptTrace、持久化分析结果——
是 command 不是 query。快照读取后续经查询接口获取已生成结果。
"""

from __future__ import annotations

from packages.domain.exceptions import NotFoundError


def run_reasoning_analysis(paper_id) -> dict:
    """推理链深度分析"""
    from packages.ai.reasoning_service import ReasoningService

    return ReasoningService().analyze(paper_id)


def analyze_paper_figures(paper_id, pdf_path: str, *, max_figures: int = 10) -> list:
    """提取并解读论文图表，返回分析结果列表"""
    from packages.ai.figure_service import FigureService

    return FigureService().analyze_paper_figures(paper_id, pdf_path, max_figures=max_figures)


def paper_reasoning_report(paper_id) -> dict:
    """推理链深度分析（先校验论文存在 → NotFoundError）"""
    from packages.ai.reasoning_service import ReasoningService
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    with session_scope() as session:
        try:
            PaperRepository(session).get_by_id(paper_id)
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
    return ReasoningService().analyze(paper_id)
