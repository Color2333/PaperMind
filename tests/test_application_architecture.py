"""application 层架构守卫（REVIEW P1-3）

queries/ 必须是纯读快照：不得触发 LLM 生成、写 PromptTrace 或更新领域状态。
生成/写操作一律放 commands/。本测试以源码扫描阻止已知写服务回流 queries。
"""

from __future__ import annotations

from pathlib import Path

QUERIES_DIR = Path(__file__).resolve().parents[1] / "packages" / "application" / "queries"

# 已知"有副作用/有成本"的服务与写函数——出现在 queries 即失败
FORBIDDEN_IN_QUERIES = [
    "ReasoningService",
    "FigureService",
    "WritingService",
    "KeywordService",
    "DailyBriefService",
    "AutoReadService",
    "update_subscription(",
    "def suggest_keywords",
    "def writing_process",
    "def run_reasoning_analysis",
    "def analyze_paper_figures",
    "def get_paper_wiki",
    "def get_topic_wiki",
    "def detect_research_gaps",
]


def test_queries_stay_read_only():
    offenders: list[str] = []
    for path in sorted(QUERIES_DIR.glob("*.py")):
        src = path.read_text()
        for token in FORBIDDEN_IN_QUERIES:
            if token in src:
                offenders.append(f"{path.name}: {token}")
    assert not offenders, "queries 层混入了生成/写语义：\n" + "\n".join(offenders)


def test_commands_cover_generation_surface():
    """生成/写语义在 commands 层就位（防搬移回退）"""
    commands_dir = Path(__file__).resolve().parents[1] / "packages" / "application" / "commands"
    all_src = "\n".join(p.read_text() for p in commands_dir.glob("*.py"))
    for token in [
        "def run_reasoning_analysis",
        "def analyze_paper_figures",
        "def writing_process",
        "def suggest_keywords",
        "def get_paper_wiki",
        "def get_topic_wiki",
        "def detect_research_gaps",
        "def update_subscription",
    ]:
        assert token in all_src, f"commands 层缺少生成/写入口: {token}"
