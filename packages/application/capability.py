"""capability metadata 导出（E5，设计④ §6）与 permission profiles 校验（E6）。

capability metadata 是 HTTP/MCP/CLI/Local UI/Full Web 的单一事实源：
- Python 侧定义 → 构建期导出 JSON → TS 侧生成类型（设计⑤ §2）。
- permission profiles 三档（research 默认 / --workspace / --coding），
  Demo 永不开放 coding（设计④ §6 硬规则）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# ---------- capability metadata ----------


@dataclass
class CapabilityMeta:
    name: str
    kind: str  # "query" | "command" | "start_job"
    risk: str  # "read_only" | "write" | "destructive"
    required_scope: str  # research:read / research:write / jobs:control / admin
    supports_async: bool
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    render_hint: str = ""
    surfaces: dict[str, str] = field(default_factory=dict)


# 设计② §2 用例目录的 capability metadata（核心子集）
CAPABILITY_METADATA: list[CapabilityMeta] = [
    CapabilityMeta(
        name="search_papers",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="paper_list",
        surfaces={"terminal": "command", "mcp": "tool", "full_web": "GET /papers/search-multi"},
    ),
    CapabilityMeta(
        name="get_paper",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="paper_card",
        surfaces={
            "terminal": "command",
            "local_ui": "PaperDetail",
            "full_web": "GET /papers/{id}",
            "mcp": "tool",
        },
    ),
    CapabilityMeta(
        name="get_research_question",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="question_card",
        surfaces={
            "terminal": "command",
            "local_ui": "ClaimWorkspace",
            "full_web": "GET /research/questions/{id}",
            "mcp": "resource",
        },
    ),
    CapabilityMeta(
        name="list_claims",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="claim_list",
        surfaces={
            "terminal": "command",
            "local_ui": "ClaimWorkspace",
            "full_web": "GET /research/questions/{id}/claims",
            "mcp": "resource",
        },
    ),
    CapabilityMeta(
        name="get_claim_evidence",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="claim_evidence_card",
        surfaces={
            "terminal": "command",
            "local_ui": "ClaimEvidencePanel",
            "full_web": "GET /research/claims/{id}/evidence",
            "mcp": "resource",
        },
    ),
    CapabilityMeta(
        name="diff_research_state",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="research_diff",
        surfaces={
            "terminal": "command",
            "local_ui": "ResearchDiff",
            "full_web": "GET /research/questions/{id}/diff",
            "mcp": "resource",
        },
    ),
    CapabilityMeta(
        name="export_research_object",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="research_pack",
        surfaces={
            "terminal": "command",
            "local_ui": "ResearchPack",
            "full_web": "GET /research/questions/{id}/export",
            "mcp": "resource",
        },
    ),
    CapabilityMeta(
        name="import_paper",
        kind="command",
        risk="write",
        required_scope="research:write",
        supports_async=True,
        render_hint="import_progress",
        surfaces={"terminal": "command", "full_web": "POST /ingest/arxiv", "mcp": "tool"},
    ),
    CapabilityMeta(
        name="start_skim",
        kind="start_job",
        risk="write",
        required_scope="research:write",
        supports_async=True,
        render_hint="job_progress",
        surfaces={"terminal": "command", "full_web": "POST /pipelines/skim/{id}", "mcp": "tool"},
    ),
    CapabilityMeta(
        name="start_deep_read",
        kind="start_job",
        risk="write",
        required_scope="research:write",
        supports_async=True,
        render_hint="job_progress",
        surfaces={"terminal": "command", "full_web": "POST /pipelines/deep/{id}", "mcp": "tool"},
    ),
    CapabilityMeta(
        name="confirm_claim",
        kind="command",
        risk="write",
        required_scope="research:write",
        supports_async=False,
        render_hint="claim_card",
        surfaces={
            "terminal": "command",
            "local_ui": "ClaimWorkspace",
            "full_web": "POST（application command）",
        },
    ),
    CapabilityMeta(
        name="cancel_job",
        kind="command",
        risk="write",
        required_scope="jobs:control",
        supports_async=False,
        surfaces={
            "terminal": "command",
            "local_ui": "JobMonitor",
            "full_web": "POST /jobs/{id}/cancel",
        },
    ),
    # ---------- E10 扩展：补全设计②用例目录的核心能力 ----------
    CapabilityMeta(
        name="ask_knowledge_base",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="answer_card",
        surfaces={"terminal": "command", "mcp": "tool", "full_web": "POST /rag/ask"},
    ),
    CapabilityMeta(
        name="get_daily_brief",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="brief_card",
        surfaces={"terminal": "command", "mcp": "tool", "full_web": "GET /brief"},
    ),
    CapabilityMeta(
        name="get_similar_papers",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="paper_list",
        surfaces={"terminal": "command", "mcp": "tool", "full_web": "GET /papers/{id}/similar"},
    ),
    CapabilityMeta(
        name="get_recommendations",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="paper_list",
        surfaces={"terminal": "command", "mcp": "tool", "full_web": "GET /papers/recommended"},
    ),
    CapabilityMeta(
        name="list_topics",
        kind="query",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="topic_list",
        surfaces={"terminal": "command", "mcp": "tool", "full_web": "GET /topics"},
    ),
    CapabilityMeta(
        name="start_daily_brief",
        kind="start_job",
        risk="write",
        required_scope="research:write",
        supports_async=True,
        render_hint="job_progress",
        surfaces={"terminal": "command", "full_web": "POST /brief/daily", "mcp": "tool"},
    ),
    CapabilityMeta(
        name="start_topic_research",
        kind="start_job",
        risk="write",
        required_scope="research:write",
        supports_async=True,
        render_hint="job_progress",
        surfaces={"terminal": "command", "full_web": "POST /topics/{id}/fetch"},
    ),
    CapabilityMeta(
        name="export_research_pack",
        kind="command",
        risk="read_only",
        required_scope="research:read",
        supports_async=False,
        render_hint="research_pack",
        surfaces={
            "terminal": "command",
            "local_ui": "ResearchPack",
            "full_web": "GET /research/questions/{id}/export",
        },
    ),
    CapabilityMeta(
        name="manage_subscription",
        kind="command",
        risk="write",
        required_scope="research:write",
        supports_async=False,
        surfaces={"terminal": "command", "full_web": "POST /topics"},
    ),
]


def export_capability_metadata() -> str:
    """导出 capability metadata 为 JSON（构建期供 TS 侧消费）"""
    data = {
        "schema_version": 1,
        "capabilities": [asdict(c) for c in CAPABILITY_METADATA],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def get_capability(name: str) -> CapabilityMeta:
    for c in CAPABILITY_METADATA:
        if c.name == name:
            return c
    raise KeyError(f"capability {name} 未注册")


# ---------- permission profiles（E6）----------

SCOPE_HIERARCHY = ["research:read", "research:write", "jobs:control", "admin"]

PROFILES: dict[str, list[str]] = {
    "research": ["research:read", "research:write"],
    "workspace": ["research:read", "research:write"],
    "coding": ["research:read", "research:write", "jobs:control", "admin"],
    "demo": ["research:read", "research:write"],  # 有限额，无 jobs:control/admin
}


def validate_profile(profile: str) -> list[str]:
    """校验 profile 名并返回 scope 列表；非法 profile 抛 ValueError"""
    if profile not in PROFILES:
        raise ValueError(f"未知 permission profile: {profile}，可选: {list(PROFILES)}")
    return PROFILES[profile]


def check_scope(token_scopes: list[str], required: str) -> bool:
    """校验 token 是否具有所需 scope"""
    return required in token_scopes
