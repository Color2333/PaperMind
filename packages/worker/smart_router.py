CHANNEL_KEYWORDS = {
    "arxiv": [
        "ml",
        "machine learning",
        "deep learning",
        "neural",
        "transformer",
        "nlp",
        "cv",
        "computer vision",
        "artificial intelligence",
        "reinforcement learning",
        "supervised",
        "unsupervised",
    ],
    "semantic_scholar": [
        "ai",
        "ml",
        "citation",
        "tldr",
        "summary",
        "impact",
        "influential",
    ],
    "dblp": [
        "nips",
        "icml",
        "cvpr",
        "iccv",
        "acl",
        "emnlp",
        "neurips",
        "conference",
        "paper",
    ],
    "ieee": [
        "ieee",
        "signal processing",
        "wireless",
        "5g",
        "6g",
        "iot",
        "circuit",
        "power",
    ],
    "biorxiv": [
        "crispr",
        "gene",
        "protein",
        "biology",
        "bioinformatics",
        "neuroscience",
        "genome",
        "cell",
        "bio",
    ],
    "openalex": ["*"],
}

CHANNEL_NEGATIVE_KEYWORDS = {
    "ieee": ["not ieee", "exclude ieee"],
    "arxiv": ["not arxiv", "exclude arxiv"],
    "biorxiv": ["not biology", "exclude biology"],
}

DEFAULT_CHANNELS = ["arxiv"]


def suggest_channels(query: str, available_channels: list[str]) -> tuple[list[str], list[str], str]:
    query_lower = query.lower()
    recommended = []
    alternatives = []
    reasoning_parts = []

    for channel, keywords in CHANNEL_KEYWORDS.items():
        if channel not in available_channels:
            continue

        score = 0
        for kw in keywords:
            if kw == "*":
                score += 1
                continue
            if kw in query_lower:
                score += 1

        if score > 0:
            if score >= 2:
                recommended.append(channel)
                reasoning_parts.append(f"{channel} 匹配 {score} 个关键词")
            else:
                alternatives.append(channel)

    if not recommended and available_channels:
        recommended = [ch for ch in DEFAULT_CHANNELS if ch in available_channels]
        if not recommended and available_channels:
            recommended = ["arxiv"]
        reasoning_parts.append("使用默认渠道")

    return (
        recommended,
        alternatives,
        "; ".join(reasoning_parts) if reasoning_parts else "无特定匹配",
    )


def suggest_channels_with_intent(
    query: str, available_channels: list[str], exclude_channels: list[str] | None = None
) -> tuple[list[str], list[str], str]:
    """
    基于意图的智能渠道推荐（支持否定关键词）

    Args:
        query: 用户查询
        available_channels: 可用渠道列表
        exclude_channels: 排除渠道列表（可选）

    Returns:
        tuple[list[str], list[str], str]: (推荐渠道，备选渠道，推荐理由)

    示例:
    >>> suggest_channels_with_intent("5G wireless NOT IEEE", ["arxiv", "ieee"])
    (['arxiv'], ['ieee'], 'arxiv 匹配 2 个关键词; ieee 被否定关键词排除')
    """
    if exclude_channels is None:
        exclude_channels = []

    query_lower = query.lower()
    recommended = []
    alternatives = []
    reasoning_parts = []

    for channel, keywords in CHANNEL_KEYWORDS.items():
        if channel not in available_channels or channel in exclude_channels:
            continue

        # 检查否定关键词
        negative_keywords = CHANNEL_NEGATIVE_KEYWORDS.get(channel, [])
        is_excluded = any(neg_kw in query_lower for neg_kw in negative_keywords)

        if is_excluded:
            reasoning_parts.append(f"{channel} 被否定关键词排除")
            continue

        score = 0
        for kw in keywords:
            if kw == "*":
                score += 1
                continue
            if kw in query_lower:
                score += 1

        if score > 0:
            if score >= 2:
                recommended.append(channel)
                reasoning_parts.append(f"{channel} 匹配 {score} 个关键词")
            else:
                alternatives.append(channel)

    if not recommended and available_channels:
        recommended = [ch for ch in DEFAULT_CHANNELS if ch in available_channels]
        if not recommended and available_channels:
            recommended = ["arxiv"]
        reasoning_parts.append("使用默认渠道")

    return (
        recommended,
        alternatives,
        "; ".join(reasoning_parts) if reasoning_parts else "无特定匹配",
    )
