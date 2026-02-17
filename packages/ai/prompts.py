"""
LLM Prompt 模板
@author Bamzc
"""


def build_skim_prompt(title: str, abstract: str) -> str:
    return (
        "你是科研助手。请根据标题和摘要输出严格 JSON：\n"
        '{"one_liner":"...", '
        '"innovations":["...","...","..."], '
        '"keywords":["keyword1","keyword2","keyword3","keyword4","keyword5"], '
        '"title_zh":"中文标题翻译", '
        '"abstract_zh":"中文摘要翻译（完整翻译，不要缩写）", '
        '"relevance_score":0.0}\n'
        "要求：\n"
        "- relevance_score 在 0 到 1 之间\n"
        "- keywords 提取 3~8 个最具代表性的英文学术关键词\n"
        "- title_zh 和 abstract_zh 为高质量中文翻译\n"
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


def build_topic_wiki_prompt(
    keyword: str,
    paper_contexts: list[dict],
    milestones: list[dict],
    seminal: list[dict],
    survey_summary: dict | None = None,
) -> str:
    """构建主题 Wiki 生成 prompt，喂入真实论文数据"""
    paper_section = ""
    for i, p in enumerate(paper_contexts[:25], 1):
        paper_section += (
            f"\n[P{i}] {p['title']}"
            f" ({p.get('year', '?')})"
            f"\nAbstract: {p.get('abstract', 'N/A')[:400]}"
            f"\nAnalysis: {p.get('analysis', 'N/A')[:400]}\n"
        )

    milestone_text = "\n".join(
        f"- {m['year']}: {m['title']} "
        f"(seminal_score={m['seminal_score']:.3f})"
        for m in milestones[:15]
    )
    seminal_text = "\n".join(
        f"- {s['title']} "
        f"(year={s['year']}, score={s['seminal_score']:.3f})"
        for s in seminal[:10]
    )

    survey_hint = ""
    if survey_summary:
        survey_hint = (
            f"\n参考综述: {survey_summary.get('overview', '')[:600]}\n"
            f"发展阶段: {survey_summary.get('stages', [])}\n"
        )

    return (
        "你是一位世界顶级的学术综述作者和知识百科编辑。"
        "请基于以下真实论文数据和分析结果，撰写一篇全面、深入、"
        "结构清晰的主题百科文章。\n\n"
        "## 输出要求\n"
        "请输出严格的 JSON 对象，结构如下：\n"
        "```json\n"
        "{\n"
        '  "overview": "主题概述（1000-2000字，涵盖定义、重要性、'
        '核心思想、发展脉络，需深入展开）",\n'
        '  "sections": [\n'
        '    {\n'
        '      "title": "章节标题",\n'
        '      "content": "章节内容（800-1500字，引用具体论文，'
        '用[P1][P2]标记引用来源，深度分析）"\n'
        "    }\n"
        "  ],\n"
        '  "key_findings": [\n'
        '    "重要发现1（引用来源论文）",\n'
        '    "重要发现2"\n'
        "  ],\n"
        '  "methodology_evolution": "方法论演化描述（500-1000字）",\n'
        '  "future_directions": [\n'
        '    "未来方向1",\n'
        '    "未来方向2"\n'
        "  ],\n"
        '  "reading_list": [\n'
        '    {"title": "论文标题", "year": 2020, '
        '"reason": "推荐理由"}\n'
        "  ]\n"
        "}\n```\n\n"
        "## 写作要求\n"
        "1. 必须基于提供的真实论文数据，引用具体论文（用[P1][P2]标记）\n"
        "2. sections 至少包含 4-6 个章节，覆盖：起源与背景、核心方法、"
        "关键变体与改进、应用场景、挑战与局限\n"
        "3. 用学术但易懂的语言，中文撰写\n"
        "4. 每个章节需要有深度分析，不是简单罗列\n"
        "5. reading_list 至少推荐 5 篇关键论文\n\n"
        f"## 主题关键词: {keyword}\n\n"
        f"## 里程碑论文:\n{milestone_text}\n\n"
        f"## 最具影响力论文:\n{seminal_text}\n\n"
        f"{survey_hint}"
        f"## 论文数据库:\n{paper_section}\n"
    )


def build_paper_wiki_prompt(
    title: str,
    abstract: str,
    analysis: str,
    related_papers: list[dict],
    ancestors: list[str],
    descendants: list[str],
) -> str:
    """构建论文 Wiki 生成 prompt"""
    related_section = ""
    for i, p in enumerate(related_papers[:10], 1):
        related_section += (
            f"\n[R{i}] {p['title']}"
            f" ({p.get('year', '?')})"
            f"\nAbstract: {p.get('abstract', 'N/A')[:300]}\n"
        )

    ancestor_text = "\n".join(
        f"- {a}" for a in ancestors[:15]
    ) or "暂无引用数据"
    descendant_text = "\n".join(
        f"- {d}" for d in descendants[:15]
    ) or "暂无被引数据"

    return (
        "你是一位学术百科编辑。请基于以下论文信息，撰写一篇"
        "全面的论文百科页面。\n\n"
        "## 输出要求\n"
        "请输出严格的 JSON 对象：\n"
        "```json\n"
        "{\n"
        '  "summary": "论文核心摘要（600-1000字，'
        '用通俗语言深度解释研究动机、方法、贡献）",\n'
        '  "contributions": ["贡献1", "贡献2", "贡献3"],\n'
        '  "methodology": "方法论详述（800-1500字）",\n'
        '  "significance": "学术意义与影响力分析（400-800字，'
        '结合引用关系）",\n'
        '  "limitations": ["局限性1", "局限性2"],\n'
        '  "related_work_analysis": "相关工作分析'
        '（500-1000字，引用[R1][R2]等标记）",\n'
        '  "reading_suggestions": [\n'
        '    {"title": "推荐论文", "reason": "理由"}\n'
        "  ]\n"
        "}\n```\n\n"
        f"## 论文标题: {title}\n\n"
        f"## 摘要:\n{abstract}\n\n"
        f"## 已有分析:\n{analysis or '暂无'}\n\n"
        f"## 引用的论文（祖先）:\n{ancestor_text}\n\n"
        f"## 被引用（后代）:\n{descendant_text}\n\n"
        f"## 相关论文:\n{related_section}\n"
    )


def build_reasoning_prompt(
    title: str,
    abstract: str,
    extracted_text: str,
    analysis_context: str = "",
) -> str:
    """构建推理链深度分析 prompt，引导 LLM 分步推理"""
    return (
        "你是一位顶级论文审稿专家和方法论分析师。请对以下论文进行深度推理链分析。\n\n"
        "## 分析方法\n"
        "请按照以下推理步骤，逐步深入分析。每一步都需要展示你的思考过程。\n\n"
        "## 输出要求\n"
        "请输出严格的 JSON 对象：\n"
        "```json\n"
        "{\n"
        '  "reasoning_steps": [\n'
        "    {\n"
        '      "step": "步骤名称",\n'
        '      "thinking": "推理思考过程（详细展开）",\n'
        '      "conclusion": "该步骤的结论"\n'
        "    }\n"
        "  ],\n"
        '  "method_chain": {\n'
        '    "problem_definition": "问题定义与动机分析",\n'
        '    "core_hypothesis": "核心假设",\n'
        '    "method_derivation": "方法推导过程（为什么选择这种方法）",\n'
        '    "theoretical_basis": "理论基础",\n'
        '    "innovation_analysis": "创新性多维评估"\n'
        "  },\n"
        '  "experiment_chain": {\n'
        '    "experimental_design": "实验设计合理性评估",\n'
        '    "baseline_fairness": "基线对比公平性分析",\n'
        '    "result_validation": "结果可靠性验证",\n'
        '    "ablation_insights": "消融实验洞察"\n'
        "  },\n"
        '  "impact_assessment": {\n'
        '    "novelty_score": 0.0,\n'
        '    "rigor_score": 0.0,\n'
        '    "impact_score": 0.0,\n'
        '    "overall_assessment": "综合评估（200-400字）",\n'
        '    "strengths": ["优势1", "优势2"],\n'
        '    "weaknesses": ["不足1", "不足2"],\n'
        '    "future_suggestions": ["建议1", "建议2"]\n'
        "  }\n"
        "}\n```\n\n"
        "## 推理步骤要求\n"
        "reasoning_steps 至少包含以下 5 个步骤：\n"
        "1. **问题理解** — 这篇论文要解决什么问题？为什么重要？\n"
        "2. **方法推导** — 作者的方法是如何一步步推导出来的？核心创新在哪？\n"
        "3. **理论验证** — 方法的理论基础是否扎实？有无逻辑漏洞？\n"
        "4. **实验评估** — 实验设计是否合理？结果是否令人信服？\n"
        "5. **影响预测** — 这篇论文对领域的潜在影响和后续可能的研究方向\n\n"
        "## 评分标准\n"
        "novelty_score / rigor_score / impact_score 均为 0-1 之间的浮点数：\n"
        "- 0.0-0.3: 低（常规/已有工作的小改进）\n"
        "- 0.3-0.6: 中等（有一定新意/较好的实验）\n"
        "- 0.6-0.8: 高（显著创新/严格的验证）\n"
        "- 0.8-1.0: 极高（突破性工作/领域里程碑）\n\n"
        "请用中文回答，展示完整推理过程。\n\n"
        f"## 论文标题: {title}\n\n"
        f"## 摘要:\n{abstract}\n\n"
        f"## 全文摘录:\n{extracted_text[:6000]}\n\n"
        + (f"## 已有分析:\n{analysis_context[:2000]}\n" if analysis_context else "")
    )


def build_research_gaps_prompt(
    keyword: str,
    papers_data: list[dict],
    network_stats: dict,
) -> str:
    """构建研究空白识别 prompt"""
    paper_lines = []
    for i, p in enumerate(papers_data[:30], 1):
        paper_lines.append(
            f"[P{i}] {p.get('title', 'N/A')} ({p.get('year', '?')})\n"
            f"  Keywords: {', '.join(p.get('keywords', []))}\n"
            f"  Abstract: {p.get('abstract', '')[:300]}\n"
            f"  indegree={p.get('indegree', 0)}, outdegree={p.get('outdegree', 0)}"
        )
    papers_text = "\n".join(paper_lines)

    return (
        "你是一位资深的学术研究战略分析师。请基于以下领域论文数据和引用网络统计，"
        "识别该领域中尚未被充分探索的研究空白和潜在机会。\n\n"
        "## 输出要求\n"
        "请输出严格的 JSON 对象：\n"
        "```json\n"
        "{\n"
        '  "research_gaps": [\n'
        "    {\n"
        '      "gap_title": "研究空白标题",\n'
        '      "description": "详细描述（200-400字）",\n'
        '      "evidence": "为什么认为这是空白（引用论文数据）",\n'
        '      "potential_impact": "填补该空白的潜在影响",\n'
        '      "suggested_approach": "建议的研究方向",\n'
        '      "difficulty": "easy/medium/hard",\n'
        '      "confidence": 0.0\n'
        "    }\n"
        "  ],\n"
        '  "method_comparison": {\n'
        '    "dimensions": ["维度1", "维度2"],\n'
        '    "methods": [\n'
        '      {"name": "方法名", "scores": {"维度1": "强/中/弱"}, "papers": ["P1"]}\n'
        "    ],\n"
        '    "underexplored_combinations": ["未被探索的方法组合"]\n'
        "  },\n"
        '  "trend_analysis": {\n'
        '    "hot_directions": ["热门方向"],\n'
        '    "declining_areas": ["式微方向"],\n'
        '    "emerging_opportunities": ["新兴机会"]\n'
        "  },\n"
        '  "overall_summary": "领域研究空白总结（300-500字）"\n'
        "}\n```\n\n"
        "## 分析要求\n"
        "1. research_gaps 至少识别 3-5 个研究空白\n"
        "2. confidence 为 0-1，表示你对该空白判断的置信度\n"
        "3. method_comparison 构建跨论文的方法对比矩阵\n"
        "4. 基于引用网络的稀疏区域来发现空白\n"
        "5. 用中文回答\n\n"
        f"## 领域关键词: {keyword}\n\n"
        f"## 引用网络统计:\n"
        f"- 总论文数: {network_stats.get('total_papers', 0)}\n"
        f"- 引用边数: {network_stats.get('edge_count', 0)}\n"
        f"- 网络密度: {network_stats.get('density', 0):.4f}\n"
        f"- 连通比例: {network_stats.get('connected_ratio', 0):.1%}\n"
        f"- 孤立论文数: {network_stats.get('isolated_count', 0)}\n\n"
        f"## 论文数据:\n{papers_text}\n"
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


def build_wiki_outline_prompt(
    keyword: str,
    paper_summaries: list[dict],
    citation_contexts: list[str],
    scholar_metadata: list[dict],
    pdf_excerpts: list[dict],
) -> str:
    """构建 Wiki 大纲生成 prompt，输出章节规划"""
    paper_section = ""
    for i, p in enumerate(paper_summaries, 1):
        paper_section += (
            f"\n[P{i}] {p.get('title', 'N/A')} ({p.get('year', '?')})\n"
            f"Abstract: {p.get('abstract', '')[:500]}\n"
            f"Analysis: {p.get('analysis', '')[:500]}\n"
        )

    citation_section = ""
    for i, ctx in enumerate(citation_contexts, 1):
        citation_section += f"\n[C{i}] {ctx}\n"

    scholar_section = ""
    for i, s in enumerate(scholar_metadata, 1):
        parts = [f"[S{i}] {s.get('title', 'N/A')} ({s.get('year', '?')})"]
        if s.get("citationCount") is not None:
            parts.append(f"引用数: {s['citationCount']}")
        if s.get("venue"):
            parts.append(f"Venue: {s['venue']}")
        if s.get("tldr"):
            parts.append(f"TLDR: {s['tldr'][:300]}")
        scholar_section += "\n".join(parts) + "\n\n"

    pdf_section = ""
    for i, ex in enumerate(pdf_excerpts, 1):
        pdf_section += (
            f"\n[PDF{i}] {ex.get('title', 'N/A')}\n"
            f"Excerpt: {ex.get('excerpt', '')[:600]}\n"
        )

    return (
        "你是一位世界顶级的学术综述作者和知识百科编辑。"
        f"请基于以下全部资料，为「{keyword}」主题撰写一篇全面的百科文章大纲。\n\n"
        "## 输出要求\n"
        "请输出严格的 JSON 对象，结构如下：\n"
        "```json\n"
        "{\n"
        '  "title": "文章标题",\n'
        '  "outline": [\n'
        '    {\n'
        '      "section_title": "章节标题",\n'
        '      "key_points": ["要点1", "要点2"],\n'
        '      "source_refs": ["[P1]", "[P3]"]\n'
        "    }\n"
        "  ],\n"
        '  "total_sections": 6\n'
        "}\n```\n\n"
        "## 写作要求\n"
        "1. outline 必须包含 5-8 个章节，覆盖：背景与起源、核心方法、"
        "关键变体、应用场景、技术挑战、最新进展、未来方向\n"
        "2. 每个章节的 key_points 列出 2-4 个核心要点\n"
        "3. source_refs 引用相关来源（[P1][P2]、[C1][C2]、[S1][S2]、[PDF1][PDF2]）\n"
        "4. 必须基于提供的全部数据规划，不得虚构\n"
        "5. 用中文撰写\n\n"
        f"## 主题关键词: {keyword}\n\n"
        f"## 论文摘要与分析:\n{paper_section}\n\n"
        f"## 引用关系上下文:\n{citation_section}\n\n"
        f"## 学术元数据:\n{scholar_section}\n\n"
        f"## PDF 摘录:\n{pdf_section}\n"
    )


def build_wiki_section_prompt(
    keyword: str,
    section_title: str,
    key_points: list[str],
    source_refs: list[str],
    all_sources_text: str,
) -> str:
    """构建 Wiki 单章节生成 prompt，输出一个章节的完整内容"""
    points_text = "\n".join(f"- {p}" for p in key_points)
    refs_text = ", ".join(source_refs) if source_refs else "无"

    return (
        "你是一位世界顶级的学术综述作者和知识百科编辑。"
        f"请基于以下资料，为「{keyword}」主题的百科文章撰写「{section_title}」章节。\n\n"
        "## 输出要求\n"
        "请输出严格的 JSON 对象，结构如下：\n"
        "```json\n"
        "{\n"
        '  "title": "章节标题",\n'
        '  "content": "章节内容（1500-3000字，引用[P1]等标记，深度分析不是罗列）",\n'
        '  "key_insight": "本章节核心洞见（一句话）"\n'
        "}\n```\n\n"
        "## 写作要求\n"
        "1. content 必须 1500-3000 字，深度分析，不要简单罗列\n"
        "2. 必须引用 source_refs 中的来源（用[P1][P2]等标记）\n"
        "3. 用学术但易懂的中文撰写\n"
        "4. key_insight 用一句话概括本章节核心洞见\n\n"
        f"## 主题关键词: {keyword}\n\n"
        f"## 本章节标题: {section_title}\n\n"
        f"## 本章节要点:\n{points_text}\n\n"
        f"## 需引用的来源: {refs_text}\n\n"
        f"## 全部资料来源:\n{all_sources_text}\n"
    )
