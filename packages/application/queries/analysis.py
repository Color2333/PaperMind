"""论文分析查询（B6，设计②：reasoning_analysis / analyze_figures）"""

from __future__ import annotations


def run_reasoning_analysis(paper_id) -> dict:
    """推理链深度分析"""
    from packages.ai.reasoning_service import ReasoningService

    return ReasoningService().analyze(paper_id)


def analyze_paper_figures(paper_id, pdf_path: str, *, max_figures: int = 10) -> list:
    """提取并解读论文图表，返回分析结果列表"""
    from packages.ai.figure_service import FigureService

    return FigureService().analyze_paper_figures(paper_id, pdf_path, max_figures=max_figures)
