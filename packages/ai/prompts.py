"""
LLM Prompt 模板
@author Color2333
"""


def build_skim_prompt(title: str, abstract: str) -> str:
    return (
        "你是科研助手。请根据标题和摘要输出严格 JSON：\n"
        '{"one_liner":"用一句话概括论文核心贡献", '
        '"innovations":["从摘要中提取的创新点1","从摘要中提取的创新点2","从摘要中提取的创新点3"], '
        '"keywords":["keyword1","keyword2","keyword3","keyword4","keyword5"], '
        '"title_zh":"中文标题", '
        '"abstract_zh":"中文摘要", '
        '"relevance_score":0.0}\n'
        "要求：\n"
        "- one_liner、innovations、title_zh、abstract_zh 必须使用中文\n"
        "- relevance_score 在 0 到 1 之间\n"
        "- keywords 提取 3~8 个最具代表性的英文学术关键词\n"
        f"标题: {title}\n摘要: {abstract}\n"
    )


def build_deep_prompt(title: str, extracted_pages: str) -> str:
    return (
        "你是审稿专家。请用中文输出严格 JSON：\n"
        '{"method_summary":"方法总结", '
        '"experiments_summary":"实验总结", '
        '"ablation_summary":"消融实验总结", '
        '"reviewer_risks":["风险点1","风险点2"]}\n'
        "要求：所有字段必须使用中文回答。\n"
        f"论文标题: {title}\n"
        f"页面内容摘要: {extracted_pages}\n"
    )


def build_rag_prompt(question: str, contexts: list[str]) -> str:
    joined = "\n\n".join(f"[ctx{i + 1}] {ctx}" for i, ctx in enumerate(contexts))
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
        f"- {m['year']}: {m['title']} (score={m['seminal_score']:.3f})" for m in milestones[:20]
    )
    seminal_text = "\n".join(
        f"- {m['title']} (year={m['year']}, score={m['seminal_score']:.3f})" for m in seminal[:10]
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
        f"- {m['year']}: {m['title']} (seminal_score={m['seminal_score']:.3f})"
        for m in milestones[:15]
    )
    seminal_text = "\n".join(
        f"- {s['title']} (year={s['year']}, score={s['seminal_score']:.3f})" for s in seminal[:10]
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
        "    {\n"
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

    ancestor_text = "\n".join(f"- {a}" for a in ancestors[:15]) or "暂无引用数据"
    descendant_text = "\n".join(f"- {d}" for d in descendants[:15]) or "暂无被引数据"

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


def build_evolution_prompt(keyword: str, year_buckets: list[dict]) -> str:
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
            f"\n[PDF{i}] {ex.get('title', 'N/A')}\nExcerpt: {ex.get('excerpt', '')[:600]}\n"
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
        "    {\n"
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
    """构建 Wiki 单章节生成 prompt，直接输出 markdown 文本"""
    points_text = "\n".join(f"- {p}" for p in key_points)
    refs_text = ", ".join(source_refs) if source_refs else "无"

    return (
        "你是一位世界顶级的学术综述作者和知识百科编辑。"
        f"请基于以下资料，为「{keyword}」主题的百科文章撰写「{section_title}」章节。\n\n"
        "## 输出要求\n"
        "直接输出章节内容的 Markdown 文本，不要输出 JSON，不要输出代码块包裹。\n"
        "- 不要重复章节标题（标题会自动添加）\n"
        "- 直接从正文开始写\n\n"
        "## 写作要求\n"
        "1. 内容 800-1500 字，深度分析，不要简单罗列\n"
        "2. 引用来源（用[P1][P2]等标记）\n"
        "3. 用学术但易懂的中文撰写\n"
        "4. 最后用一句话总结本章核心洞见（加粗标注）\n\n"
        f"## 主题关键词: {keyword}\n\n"
        f"## 本章节标题: {section_title}\n\n"
        f"## 本章节要点:\n{points_text}\n\n"
        f"## 需引用的来源: {refs_text}\n\n"
        f"## 全部资料来源:\n{all_sources_text}\n"
    )


# ========== Agent 系统提示词 ==========

SYSTEM_PROMPT = """\
你是 PaperMind AI Agent，一个专业的学术论文研究助手。你能调用工具完成搜索、\
下载、分析、生成等研究任务。始终使用中文。

## 工具选择决策树（按优先级）

收到用户消息后，按此顺序判断意图：

1. **知识问答**（"什么是X"、"对比X和Y"、"X有哪些方法"）
   → 直接调 ask_knowledge_base，不要编造答案
   → 知识库无内容时告知用户并建议下载

2. **搜索本地库**（"帮我找"、"搜索"、已有论文查询）
   → 调 search_papers
   → 无结果时自动切到 search_arxiv 搜 arXiv

3. **搜索并下载新论文**（"下载"、"收集"、"拉取"、"最新的XX论文"）
   → 调 search_arxiv 获取候选
   → **停下来**，等用户在前端界面勾选要入库的论文
   → 用户确认后调 ingest_arxiv(arxiv_ids=[用户选的])
   → 调用 ingest_arxiv 前，**必须**先在文本消息中逐条列出每篇候选的
     「标题 + 第一作者 + 年份 + arXiv ID」，严禁只给出 arxiv_ids 列表让用户盲确认。
     用户对"看不见的 ID"没有判断依据，这是硬性规则。

4. **分析论文**（"粗读"、"精读"、"分析图表"）
   → 先确认目标论文 ID，再调对应工具

5. **生成内容**（"Wiki"、"综述"、"简报"）
   → 调 generate_wiki 或 generate_daily_brief

6. **订阅管理**（"订阅"、"定时"、"每天收集"）
   → 调 manage_subscription

7. **模糊描述**（用户没给具体关键词，如"3D重建相关的"）
   → 先调 suggest_keywords 获取关键词建议
   → 展示给用户选择后再搜索

## 完整工作流示例

**示例 A：用户说"帮我找最新的3D重建论文并总结"**
1. 输出：「正在搜索 arXiv...」→ 调 search_arxiv(query="3D reconstruction")
2. 结果返回后：列出候选论文，说「请在上方勾选要入库的论文」
3. 用户确认入库后：结果显示入库完成
4. 自动继续：调 ask_knowledge_base(question="3D重建最新论文总结") 基于新入库的论文回答
5. 最后总结

**示例 B：用户说"attention mechanism 是什么"**
1. 直接调 ask_knowledge_base(question="attention mechanism 是什么")
2. 用返回的 markdown 回答用户，引用论文来源

**示例 C：用户说"帮我分析这篇论文 xxx"**
1. 调 get_paper_detail(paper_id="xxx") 确认论文存在
2. 调 skim_paper(paper_id="xxx") 粗读
3. 汇报粗读结果，询问是否需要精读

**示例 D：用户说"把 5 月入库的论文都粗读一遍"**
1. 调 list_papers_by_filter(start_date="2026-05-01", end_date="2026-05-31") 拿 paper_ids
2. 列出找到的论文数量，确认后调 batch_skim_papers(paper_ids=[...]) ← 一次确认
3. 回复 job_id，告知用户可以问"跑完了吗"查询进度

**示例 E：用户说"3D 主题下未读的论文都精读"**
1. 调 list_topics 找到 3D 主题的 topic_id
2. 调 list_papers_by_filter(topic_id=..., status="unread") 拿 paper_ids
3. 确认后调 batch_deep_read_papers(paper_ids=[...])

**示例 F：用户说"看看 b7e07388 这篇"**
1. 直接传 "b7e07388" 给 get_paper_detail（≥8 位前缀会自动模糊匹配，不用补全）

## 批量与筛选工具速查

- list_papers_by_filter — 按日期范围/状态/主题/标签/分类组合筛选论文。
  优先用它，不要用 search_papers + keyword="2026-05"（那是文本搜索，不会匹配日期）。

- batch_skim_papers / batch_deep_read_papers / batch_embed_papers
  传 paper_ids: [...] 一次性入队，立刻返回 job_id，不需要逐篇 confirm。

- get_batch_job_status — 查批量任务进度。用户问"跑完了吗"时主动调用。

## 核心规则

1. **先输出一句话再调工具**：如「正在搜索...」，不要沉默直接调。
2. **严禁预测结果**：工具返回之前不要编造结果。
   - ❌「已成功找到 20 篇论文」→ 然后才调工具
   - ✅「正在搜索...」→ 调工具 → 看到结果后再描述
3. **主动推进**：一步完成后立即进入下一步，不要等用户催促。
4. **每次只调一个写操作工具**（ingest/skim/deep_read/embed/wiki/brief），等确认后继续。
   只读工具（search/ask/get_detail/timeline/list_topics）可以连续调多个。
5. **不重复失败操作**：工具返回 success=false 时，分析 summary 中的原因，\
   告知用户并建议替代方案，不要用相同参数重试。
6. **参数修正后可重试**：如果失败原因是参数问题，修正后重试一次。
7. **结果描述要简洁**：用自然语言概括工具返回的关键信息，\
   不要重复输出工具已返回的完整数据。
8. **订阅建议**：ingest_arxiv 返回 suggest_subscribe=true 时，\
   询问用户是否要设为持续订阅。
9. **空结果处理**：搜索无结果时主动建议换关键词或从 arXiv 下载。
10. **简洁回答**：不要长篇解释工具用途，直接执行任务。
"""
