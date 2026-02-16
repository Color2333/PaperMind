"""
LLM Prompt 模板
@author Bamzc
"""


def build_skim_prompt(title: str, abstract: str) -> str:
    return (
        "你是科研助手。请根据标题和摘要输出严格 JSON：\n"
        '{"one_liner":"...", '
        '"innovations":["...","...","..."], '
        '"relevance_score":0.0}\n'
        "要求 relevance_score 在 0 到 1 之间。\n"
        f"标题: {title}\n摘要: {abstract}\n"
    )


def build_deep_prompt(
    title: str, extracted_pages: str
) -> str:
    return (
        "你是审稿专家。请输出严格 JSON：\n"
        '{"method_summary":"...", '
        '"experiments_summary":"...", '
        '"ablation_summary":"...", '
        '"reviewer_risks":["...","..."]}\n'
        f"论文标题: {title}\n"
        f"页面内容摘要: {extracted_pages}\n"
    )


def build_rag_prompt(
    question: str, contexts: list[str]
) -> str:
    joined = "\n\n".join(
        f"[ctx{i + 1}] {ctx}"
        for i, ctx in enumerate(contexts)
    )
    return (
        "请基于上下文回答问题，输出严格 JSON："
        '{"answer":"...", "confidence":0.0}\n'
        f"问题: {question}\n上下文:\n{joined}"
    )


def build_survey_prompt(
    keyword: str,
    milestones: list[dict],
    seminal: list[dict],
) -> str:
    milestone_text = "\n".join(
        f"- {m['year']}: {m['title']} "
        f"(score={m['seminal_score']:.3f})"
        for m in milestones[:20]
    )
    seminal_text = "\n".join(
        f"- {m['title']} "
        f"(year={m['year']}, "
        f"score={m['seminal_score']:.3f})"
        for m in seminal[:10]
    )
    return (
        "你是科研综述作者。请输出严格 JSON：\n"
        '{"overview":"...", '
        '"stages":[{"name":"...","description":"..."}], '
        '"reading_list":["...","..."], '
        '"open_questions":["...","..."]}\n'
        f"主题关键词: {keyword}\n"
        f"里程碑:\n{milestone_text}\n\n"
        f"Seminal候选:\n{seminal_text}\n"
    )


def build_evolution_prompt(
    keyword: str, year_buckets: list[dict]
) -> str:
    lines = []
    for x in year_buckets:
        lines.append(
            f"- {x['year']}: "
            f"count={x['paper_count']}, "
            f"avg_score={x['avg_seminal_score']:.3f}, "
            f"top={x['top_titles']}"
        )
    joined = "\n".join(lines)
    return (
        "你是领域分析师。请基于时间桶数据输出严格 JSON：\n"
        '{"trend_summary":"...", '
        '"phase_shift_signals":["..."], '
        '"next_week_focus":["..."]}\n'
        f"关键词: {keyword}\n数据:\n{joined}\n"
    )
