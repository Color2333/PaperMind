from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from packages.domain.enums import ReadStatus


class PaperCreate(BaseModel):
    arxiv_id: str
    title: str
    abstract: str
    publication_date: date | None = None
    metadata: dict = Field(default_factory=dict)


class PaperOut(BaseModel):
    id: UUID
    arxiv_id: str
    title: str
    abstract: str
    publication_date: date | None
    read_status: ReadStatus
    pdf_path: str | None
    metadata: dict


class SkimReport(BaseModel):
    one_liner: str
    innovations: list[str]
    keywords: list[str] = []
    title_zh: str = ""
    abstract_zh: str = ""
    relevance_score: float


class DeepDiveReport(BaseModel):
    method_summary: str
    experiments_summary: str
    ablation_summary: str
    reviewer_risks: list[str]


class AskRequest(BaseModel):
    question: str
    top_k: int = 5


class AskResponse(BaseModel):
    answer: str
    cited_paper_ids: list[UUID]
    evidence: list[dict] = Field(default_factory=list)


class DailyBriefRequest(BaseModel):
    date: datetime | None = None
    recipient: str | None = None


class TopicCreate(BaseModel):
    name: str
    query: str
    enabled: bool = True
    max_results_per_run: int = 20
    retry_limit: int = 2
    schedule_frequency: str = "daily"
    schedule_time_utc: int = 21


class TopicUpdate(BaseModel):
    query: str | None = None
    enabled: bool | None = None
    max_results_per_run: int | None = None
    retry_limit: int | None = None
    schedule_frequency: str | None = None
    schedule_time_utc: int | None = None


# ---------- LLM Provider Config ----------


class LLMProviderCreate(BaseModel):
    name: str
    provider: str  # openai / anthropic / zhipu
    api_key: str
    api_base_url: str | None = None
    model_skim: str
    model_deep: str
    model_vision: str | None = None
    model_embedding: str
    model_fallback: str


class LLMProviderUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    api_key: str | None = None
    api_base_url: str | None = None
    model_skim: str | None = None
    model_deep: str | None = None
    model_vision: str | None = None
    model_embedding: str | None = None
    model_fallback: str | None = None


class LLMProviderOut(BaseModel):
    id: str
    name: str
    provider: str
    api_key_masked: str
    api_base_url: str | None
    model_skim: str
    model_deep: str
    model_vision: str | None
    model_embedding: str
    model_fallback: str
    is_active: bool


# ---------- Agent ----------


class AgentMessage(BaseModel):
    """Agent 对话消息"""

    role: str  # user / assistant / tool
    content: str = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_result: dict | None = None


class AgentChatRequest(BaseModel):
    """Agent 对话请求"""

    messages: list[AgentMessage]
    confirmed_action_id: str | None = None


class PendingAction(BaseModel):
    """等待用户确认的操作"""

    id: str
    tool: str
    args: dict
    description: str
