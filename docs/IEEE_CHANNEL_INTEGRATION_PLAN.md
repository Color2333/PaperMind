# IEEE 渠道集成升级方案

**文档版本**: v1.0  
**创建时间**: 2026-03-03  
**作者**: 老白 (Color2333)  
**状态**: 方案评审中

---

## 📋 执行摘要

本方案旨在为 PaperMind 平台集成 **IEEE Xplore** 学术论文渠道，实现从单一 ArXiv 渠道向多渠道架构的演进。方案采用**渐进式改造策略**，在保持现有 ArXiv 流程稳定运行的前提下，逐步引入 IEEE 渠道支持。

### 核心目标

1. **多渠道支持**: 支持 ArXiv + IEEE 双渠道并行抓取
2. **向后兼容**: 不破坏现有数据模型和业务逻辑
3. **成本可控**: 严格限制 IEEE API 配额，避免预算超支
4. **用户体验**: 前端透明感知，IEEE 论文特殊标识

### 技术方案选择

**方案 A - 渐进式改造（推荐）**
- 分 4 个阶段实施，总计 4-5 周
- 先改数据模型，再开发客户端，最后适配主题系统
- 风险低，可回滚，每阶段独立验证

---

## 一、现有架构分析

### 1.1 当前渠道架构

```
┌─────────────────────────────────────────────────────────────┐
│                    TopicSubscription                        │
│  (主题订阅：query + schedule + max_results)                 │
└─────────────────────┬───────────────────────────────────────┘
                      │ APScheduler 定时调度
┌─────────────────────▼───────────────────────────────────────┐
│         daily_runner.run_topic_ingest()                     │
│         (智能精读限额 + 分批处理 + 配额控制)                 │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│         PaperPipelines.ingest_arxiv()                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 1. ArxivClient.fetch_latest() - 搜索 API             │    │
│  │ 2. PaperRepository.list_existing_arxiv_ids() - 去重  │    │
│  │ 3. PaperRepository.upsert_paper() - 入库            │    │
│  │ 4. (可选) ArxivClient.download_pdf() - 下载 PDF     │    │
│  │ 5. GraphService.auto_link_citations() - 引用关联   │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 现有数据模型

**核心表结构:**

| 表名 | 关键字段 | 用途 |
|------|---------|------|
| `papers` | `arxiv_id` (unique), `title`, `abstract`, `metadata` | 论文元数据 |
| `topic_subscriptions` | `name`, `query`, `enabled`, `schedule_frequency` | 主题订阅配置 |
| `source_checkpoints` | `source`, `last_fetch_at`, `last_published_date` | 增量抓取检查点 |
| `citations` | `source_paper_id`, `target_paper_id`, `context` | 引用关系 |

### 1.3 关键代码模块

| 模块 | 文件路径 | 职责 |
|------|---------|------|
| ArXiv 客户端 | `packages/integrations/arxiv_client.py` | ArXiv API 封装 |
| Pipeline | `packages/ai/pipelines.py` | 论文摄取流程编排 |
| 定时任务 | `packages/ai/daily_runner.py` | 每日自动抓取调度 |
| 数据仓库 | `packages/storage/repositories.py` | 数据持久化 |
| API 路由 | `apps/api/routers/papers.py` | REST API 接口 |

---

## 二、IEEE 集成挑战分析

### 2.1 技术挑战

#### 挑战 1: IEEE API 限制

| 对比项 | ArXiv | IEEE Xplore |
|--------|-------|-------------|
| **API 费用** | 免费 | $129/月 起（500 次/天） |
| **认证方式** | 无需认证 | API Key 必需 |
| **数据格式** | Atom XML | JSON |
| **唯一标识** | arxiv_id | IEEE Document ID / DOI |
| **增量抓取** | 支持（submittedDate） | 困难（无明确时间排序） |
| **PDF 下载** | 免费开放 | 需机构订阅/付费 |
| **速率限制** | 429（可重试） | 403（严格限制） |

#### 挑战 2: 数据模型扩展需求

**当前 `PaperCreate` schema 问题:**
```python
# ❌ 现有设计 - 强耦合 ArXiv
class PaperCreate(BaseModel):
    arxiv_id: str  # 字段名绑定 ArXiv
    title: str
    abstract: str
    metadata: dict  # 非结构化
```

**需要扩展为:**
```python
# ✅ 多渠道兼容设计
class PaperCreate(BaseModel):
    source: str = "arxiv"  # 渠道标识
    source_id: str  # 渠道唯一 ID（arxiv_id / ieee_doc_id / doi）
    doi: str | None = None  # DOI 号（可选）
    title: str
    abstract: str
    publication_date: date | None = None
    metadata: dict  # 渠道特有字段（authors, venue, publisher 等）
```

#### 挑战 3: 去重逻辑复杂化

**ArXiv 去重:**
- 简单：`arxiv_id` 唯一性检查
- 性能：O(1) 索引查找

**IEEE 去重:**
- 复杂：需要支持 DOI、IEEE ID、标题模糊匹配
- 性能：O(log n) 或 O(n)
- 跨渠道去重：同一篇论文可能在 ArXiv 和 IEEE 都存在

#### 挑战 4: PDF 下载权限控制

**ArXiv:**
```python
url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"  # 直接下载
```

**IEEE:**
- 需要认证（机构订阅）
- 有 DRM 保护
- 下载的是带水印 PDF
- 很多论文只提供摘要（全文需付费）

### 2.2 对现有功能的影响

| 功能模块 | 影响程度 | 需要修改的内容 |
|---------|---------|---------------|
| **数据模型** | 🔴 高 | `papers` 表添加 `source`、`doi` 字段，修改唯一约束 |
| **主题订阅** | 🟡 中 | `topic_subscriptions` 添加 `sources` 字段（支持多渠道） |
| **定时任务** | 🟡 中 | `daily_runner` 需要支持 IEEE 配额管理 |
| **PDF 阅读** | 🟡 中 | IEEE PDF 特殊标识（可能需付费） |
| **引用图谱** | 🟢 低 | 使用 DOI 适配 Semantic Scholar |
| **RAG 问答** | 🟢 低 | 无需修改 |
| **Wiki 生成** | 🟢 低 | 无需修改 |

---

## 三、IEEE 集成方案设计

### 3.1 总体架构设计

```
┌─────────────────────────────────────────────────────────────────┐
│                      TopicSubscription                          │
│  sources: ["arxiv", "ieee"]  ← 新增多渠道支持                   │
└─────────────────┬───────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────┐
│              ChannelOrchestrator (新增编排层)                    │
│  ┌─────────────────┐  ┌─────────────────┐                      │
│  │ ArXiv Channel   │  │ IEEE Channel    │                      │
│  │ (现有)          │  │ (新增)          │                      │
│  └────────┬────────┘  └────────┬────────┘                      │
└───────────┼─────────────────────┼───────────────────────────────┘
            │                     │
┌───────────▼─────────────────────▼───────────────────────────────┐
│              PaperPipelines.ingest_channel()                     │
│  (统一摄取接口，适配多渠道)                                      │
└───────────┬─────────────────────┬───────────────────────────────┘
            │                     │
┌───────────▼──────────┐  ┌──────▼───────────────────────────────┐
│   ArxivClient        │  │   IeeeClient (新增)                   │
│   - fetch_latest     │  │   - fetch_by_keywords                │
│   - fetch_by_ids     │  │   - fetch_metadata                   │
│   - download_pdf     │  │   - download_pdf (受限)              │
└──────────────────────┘  └───────────────────────────────────────┘
```

### 3.2 分阶段实施计划

#### 阶段一：基础设施改造（1-2 周）

**任务 1.1: 扩展数据模型**

**1.1.1 修改 `PaperCreate` schema**
```python
# 文件：packages/domain/schemas.py
class PaperCreate(BaseModel):
    # 新增字段（多渠道兼容）
    source: str = "arxiv"  # arxiv / ieee / doi
    source_id: str  # 渠道唯一 ID
    doi: str | None = None
    
    # 保留字段（向后兼容）
    arxiv_id: str | None = None  # 标记为 nullable
    title: str
    abstract: str
    publication_date: date | None = None
    metadata: dict = Field(default_factory=dict)
```

**1.1.2 修改 `papers` 表模型**
```python
# 文件：packages/storage/models.py
class Paper(Base):
    __tablename__ = "papers"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    
    # 新增字段
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="arxiv", index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    doi: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    
    # 保留字段（向后兼容）
    arxiv_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    
    # ... 其他字段保持不变
    
    # 联合唯一约束
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_paper_source"),
        Index("ix_papers_doi", "doi", unique=True),
    )
```

**1.1.3 创建数据库迁移脚本**
```python
# 文件：infra/migrations/versions/20260303_0009_add_ieee_channel.py
"""add ieee channel support

Revision ID: 20260303_0009
Revises: 20260228_0008_agent_conversations
Create Date: 2026-03-03

"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # 1. 添加新字段
    op.add_column('papers', sa.Column('source', sa.String(32), nullable=False, server_default='arxiv'))
    op.add_column('papers', sa.Column('source_id', sa.String(128), nullable=True))
    op.add_column('papers', sa.Column('doi', sa.String(128), nullable=True))
    
    # 2. 将现有 arxiv_id 复制到 source_id
    op.execute("UPDATE papers SET source_id = arxiv_id WHERE source_id IS NULL")
    
    # 3. 修改 arxiv_id 为 nullable
    op.alter_column('papers', 'arxiv_id', existing_type=sa.String(64), nullable=True)
    
    # 4. 创建索引
    op.create_index('ix_papers_source', 'papers', ['source'])
    op.create_index('ix_papers_source_id', 'papers', ['source_id'])
    op.create_index('ix_papers_doi', 'papers', ['doi'])
    
    # 5. 创建联合唯一约束
    op.create_unique_constraint('uq_paper_source', 'papers', ['source', 'source_id'])

def downgrade():
    op.drop_constraint('uq_paper_source', 'papers', type_='unique')
    op.drop_index('ix_papers_doi', 'papers')
    op.drop_index('ix_papers_source_id', 'papers')
    op.drop_index('ix_papers_source', 'papers')
    op.alter_column('papers', 'arxiv_id', existing_type=sa.String(64), nullable=False)
    op.drop_column('papers', 'doi')
    op.drop_column('papers', 'source_id')
    op.drop_column('papers', 'source')
```

**任务 1.2: 开发 IEEE 客户端**

```python
# 文件：packages/integrations/ieee_client.py
"""
IEEE Xplore API 客户端
注意：需要 API Key（免费版 50 次/天，付费版$129/月起）
文档：https://developer.ieee.org/docs
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx

from packages.domain.schemas import PaperCreate

logger = logging.getLogger(__name__)

IEEE_API_BASE = "https://ieeexploreapi.ieee.org/api/v1"
RETRY_CODES = {429, 500, 502, 503}
MAX_RETRIES = 3
BASE_DELAY = 2.0


@dataclass
class IeeePaperData:
    """IEEE 论文数据结构"""
    ieee_doc_id: str  # IEEE Document ID
    doi: str | None
    title: str
    abstract: str
    authors: list[str]
    publication_date: date | None
    venue: str | None  # 期刊/会议名称
    publisher: str
    isbn: str | None
    issn: str | None
    pdf_available: bool = False


class IeeeClient:
    """IEEE Xplore REST API 封装"""
    
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client: httpx.Client | None = None
    
    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=IEEE_API_BASE,
                timeout=20,
                headers={"apikey": self.api_key},
                follow_redirects=True,
            )
        return self._client
    
    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """带重试的 GET 请求"""
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.client.get(path, params=params)
                if resp.status_code in RETRY_CODES:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "IEEE API %d, retry %d/%d in %.1fs",
                        resp.status_code, attempt + 1, MAX_RETRIES, delay
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                logger.warning("IEEE API timeout for %s", path)
                time.sleep(BASE_DELAY)
            except Exception as exc:
                logger.warning("IEEE API error for %s: %s", path, exc)
                return None
        logger.error("IEEE API exhausted retries for %s", path)
        return None
    
    def fetch_by_keywords(
        self,
        query: str,
        max_results: int = 20,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[PaperCreate]:
        """
        按关键词搜索 IEEE 论文
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数（1-200）
            start_year: 起始年份（可选）
            end_year: 结束年份（可选）
        
        Returns:
            list[PaperCreate]: 论文元数据列表
        """
        params = {
            "querytext": query,
            "max_records": min(max_results, 200),
            "start_record": 1,
        }
        
        if start_year:
            params["start_year"] = start_year
        if end_year:
            params["end_year"] = end_year
        
        data = self._get("/search", params=params)
        if not data or "articles" not in data:
            return []
        
        papers = []
        for article in data["articles"]:
            paper = self._parse_article(article)
            if paper:
                papers.append(paper)
        
        return papers
    
    def fetch_by_doi(self, doi: str) -> PaperCreate | None:
        """按 DOI 获取论文元数据"""
        clean_doi = doi.replace("doi/", "").strip()
        data = self._get(f"/articles/{clean_doi}")
        if not data:
            return None
        return self._parse_article(data)
    
    def fetch_metadata(self, ieee_doc_id: str) -> PaperCreate | None:
        """按 IEEE Document ID 获取元数据"""
        data = self._get(f"/articles/{ieee_doc_id}")
        if not data:
            return None
        return self._parse_article(data)
    
    def download_pdf(self, ieee_doc_id: str) -> str | None:
        """
        下载 IEEE 论文 PDF（需要机构订阅）
        
        注意：此方法可能失败（权限限制）
        返回：PDF 本地路径 或 None
        """
        logger.warning("IEEE PDF 下载需要机构订阅，可能失败：%s", ieee_doc_id)
        # TODO: 实现 PDF 下载逻辑（需要机构认证）
        return None
    
    def _parse_article(self, article: dict) -> PaperCreate | None:
        """解析 IEEE API 响应为 PaperCreate"""
        ieee_doc_id = str(article.get("article_number", ""))
        doi = article.get("doi")
        title = (article.get("title") or "").strip()
        
        if not title:
            return None
        
        # 解析摘要
        abstract = ""
        if "abstract" in article:
            abstract = article["abstract"].strip()
        
        # 解析出版日期
        pub_date = None
        if "publication_date" in article:
            try:
                pub_date = date.fromisoformat(article["publication_date"][:10])
            except (ValueError, TypeError):
                pass
        
        # 解析作者列表
        authors = []
        for author in article.get("authors", []):
            if isinstance(author, dict) and "full_name" in author:
                authors.append(author["full_name"])
        
        # 解析期刊/会议名称
        venue = article.get("publication_title", "") or None
        
        # 解析出版商
        publisher = article.get("publisher", "IEEE")
        
        # 构建 metadata
        metadata = {
            "source": "ieee",
            "ieee_doc_id": ieee_doc_id,
            "doi": doi,
            "authors": authors,
            "venue": venue,
            "publisher": publisher,
            "isbn": article.get("isbn"),
            "issn": article.get("issn"),
        }
        
        return PaperCreate(
            source="ieee",
            source_id=ieee_doc_id,
            doi=doi,
            arxiv_id=None,  # IEEE 论文没有 arxiv_id
            title=title,
            abstract=abstract,
            publication_date=pub_date,
            metadata=metadata,
        )
    
    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()
    
    def __del__(self):
        self.close()
```

**任务 1.3: 扩展 TopicSubscription 模型**

```python
# 文件：packages/storage/models.py
class TopicSubscription(Base):
    __tablename__ = "topic_subscriptions"
    
    # ... 现有字段保持不变 ...
    
    # 新增：支持的渠道列表
    sources: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=["arxiv"]
    )
    
    # 新增：IEEE 特定配置
    ieee_daily_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10  # 每日 IEEE API 调用限额
    )
    ieee_api_key_override: Mapped[str | None] = mapped_column(
        String(512), nullable=True  # 可选的 IEEE API Key 覆盖
    )
```

**数据库迁移:**
```python
# 文件：infra/migrations/versions/20260303_0010_add_topic_sources.py
"""add topic sources support

Revision ID: 20260303_0010
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('topic_subscriptions', 
                  sa.Column('sources', sa.JSON, nullable=False, 
                           server_default='["arxiv"]'))
    op.add_column('topic_subscriptions',
                  sa.Column('ieee_daily_quota', sa.Integer, nullable=False,
                           server_default='10'))
    op.add_column('topic_subscriptions',
                  sa.Column('ieee_api_key_override', sa.String(512), nullable=True))

def downgrade():
    op.drop_column('topic_subscriptions', 'ieee_api_key_override')
    op.drop_column('topic_subscriptions', 'ieee_daily_quota')
    op.drop_column('topic_subscriptions', 'sources')
```

---

#### 阶段二：渠道适配层（1 周）

**任务 2.1: 创建渠道抽象基类**

```python
# 文件：packages/integrations/channel_base.py
"""
渠道抽象基类 - 统一多渠道接口
"""

from abc import ABC, abstractmethod
from typing import Optional

from packages.domain.schemas import PaperCreate


class ChannelBase(ABC):
    """论文渠道抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """渠道名称（arxiv / ieee）"""
        pass
    
    @abstractmethod
    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        """
        搜索论文
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数
        
        Returns:
            list[PaperCreate]: 论文元数据列表
        """
        pass
    
    @abstractmethod
    def download_pdf(self, paper_id: str) -> str | None:
        """
        下载论文 PDF
        
        Args:
            paper_id: 渠道论文 ID
        
        Returns:
            PDF 本地路径 或 None
        """
        pass
    
    @abstractmethod
    def supports_incremental(self) -> bool:
        """是否支持增量抓取"""
        pass
```

**任务 2.2: 实现渠道适配器**

```python
# 文件：packages/integrations/arxiv_channel.py
"""ArXiv 渠道适配器"""

from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.channel_base import ChannelBase
from packages.domain.schemas import PaperCreate


class ArxivChannel(ChannelBase):
    
    def __init__(self) -> None:
        self._client = ArxivClient()
    
    @property
    def name(self) -> str:
        return "arxiv"
    
    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        papers = self._client.fetch_latest(query, max_results)
        # 统一设置 source 字段
        for paper in papers:
            paper.source = "arxiv"
            paper.source_id = paper.arxiv_id
        return papers
    
    def download_pdf(self, arxiv_id: str) -> str | None:
        try:
            return self._client.download_pdf(arxiv_id)
        except Exception as exc:
            return None
    
    def supports_incremental(self) -> bool:
        return True
```

```python
# 文件：packages/integrations/ieee_channel.py
"""IEEE 渠道适配器"""

from packages.config import get_settings
from packages.integrations.ieee_client import IeeeClient
from packages.integrations.channel_base import ChannelBase
from packages.domain.schemas import PaperCreate


class IeeeChannel(ChannelBase):
    
    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self._client = IeeeClient(api_key=api_key or settings.ieee_api_key)
    
    @property
    def name(self) -> str:
        return "ieee"
    
    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        return self._client.fetch_by_keywords(query, max_results)
    
    def download_pdf(self, ieee_doc_id: str) -> str | None:
        # IEEE PDF 下载受限
        return self._client.download_pdf(ieee_doc_id)
    
    def supports_incremental(self) -> bool:
        return False  # IEEE 不支持可靠的增量抓取
```

**任务 2.3: 修改 PaperPipelines 支持多渠道**

```python
# 文件：packages/ai/pipelines.py
# 修改 ingest_arxiv 为通用 ingest_channel 方法

def ingest_channel(
    self,
    channel: ChannelBase,
    query: str,
    max_results: int = 20,
    topic_id: str | None = None,
    action_type: ActionType = ActionType.manual_collect,
) -> tuple[int, list[str], int]:
    """
    通用渠道论文摄取
    
    Args:
        channel: 渠道实例
        query: 搜索关键词
        max_results: 最大结果数
        topic_id: 可选的主题 ID
        action_type: 行动类型
    
    Returns:
        (total_count, inserted_ids, new_papers_count)
    """
    inserted_ids: list[str] = []
    new_papers_count = 0
    total_fetched = 0
    
    with session_scope() as session:
        repo = PaperRepository(session)
        run_repo = PipelineRunRepository(session)
        action_repo = ActionRepository(session)
        
        run = run_repo.start(
            f"ingest_{channel.name}",
            decision_note=f"query={query}"
        )
        
        try:
            # 从渠道获取论文
            papers = channel.fetch(query, max_results)
            total_fetched = len(papers)
            
            # 去重：检查哪些论文已存在
            # 使用 (source, source_id) 联合唯一键
            existing_ids = set()
            for paper in papers:
                existing = repo.get_by_source_and_id(
                    paper.source, paper.source_id
                )
                if existing:
                    existing_ids.add(paper.source_id)
            
            # 只处理新论文
            for paper in papers:
                if paper.source_id not in existing_ids:
                    saved = self._save_paper(repo, paper, topic_id)
                    new_papers_count += 1
                    inserted_ids.append(saved.id)
            
            # 创建行动记录
            if inserted_ids:
                action_repo.create_action(
                    action_type=action_type,
                    title=f"收集 [{channel.name}]: {query[:80]}",
                    paper_ids=inserted_ids,
                    query=query,
                    topic_id=topic_id,
                )
                
                # 后台关联引用
                threading.Thread(
                    target=_bg_auto_link,
                    args=(inserted_ids,),
                    daemon=True,
                ).start()
            
            run_repo.finish(run.id)
            
            logger.info(
                "✅ 渠道 [%s] 抓取完成：%d 篇新论文（从 %d 篇中筛选）",
                channel.name, new_papers_count, total_fetched
            )
            
            return len(inserted_ids), inserted_ids, new_papers_count
            
        except Exception as exc:
            run_repo.fail(run.id, str(exc))
            raise


# 保留 ingest_arxiv 作为兼容方法
def ingest_arxiv(
    self,
    query: str,
    max_results: int = 20,
    topic_id: str | None = None,
    action_type: ActionType = ActionType.manual_collect,
) -> tuple[int, list[str], int]:
    from packages.integrations.arxiv_channel import ArxivChannel
    channel = ArxivChannel()
    return self.ingest_channel(
        channel=channel,
        query=query,
        max_results=max_results,
        topic_id=topic_id,
        action_type=action_type,
    )
```

---

#### 阶段三：主题系统扩展（1 周）

**任务 3.1: 修改定时任务调度**

```python
# 文件：packages/ai/daily_runner.py
# 修改 run_topic_ingest 支持多渠道

def run_topic_ingest(topic_id: str) -> dict:
    """
    单独处理一个主题的抓取 - 支持多渠道
    """
    pipelines = PaperPipelines()
    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            return {"topic_id": topic_id, "status": "not_found"}
        
        topic_name = topic.name
        sources = topic.sources or ["arxiv"]  # 默认只有 ArXiv
        
        # 按渠道分别抓取
        all_results = {}
        for source in sources:
            if source == "arxiv":
                result = ingest_from_arxiv(
                    pipelines, topic, session
                )
            elif source == "ieee":
                result = ingest_from_ieee(
                    pipelines, topic, session
                )
            else:
                logger.warning("未知渠道：%s", source)
                continue
            
            all_results[source] = result
        
        # 汇总统计
        total_inserted = sum(
            r.get("inserted", 0) for r in all_results.values()
        )
        
        return {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "sources": sources,
            "total_inserted": total_inserted,
            "by_source": all_results,
        }


def ingest_from_arxiv(pipelines, topic, session) -> dict:
    """ArXiv 渠道抓取（保持现有逻辑）"""
    # ... 现有代码保持不变 ...
    pass


def ingest_from_ieee(pipelines, topic, session) -> dict:
    """IEEE 渠道抓取 - 独立配额控制"""
    from packages.integrations.ieee_channel import IeeeChannel
    from packages.config import get_settings
    
    settings = get_settings()
    
    # 检查 IEEE 配额
    ieee_quota = getattr(topic, "ieee_daily_quota", 10)
    if ieee_quota <= 0:
        logger.info("主题 [%s] IEEE 配额已用尽", topic.name)
        return {"status": "quota_exhausted", "inserted": 0}
    
    # 使用 IEEE 渠道抓取
    channel = IeeeChannel(
        api_key=getattr(topic, "ieee_api_key_override", None)
    )
    
    try:
        total, inserted_ids, new_count = pipelines.ingest_channel(
            channel=channel,
            query=topic.query,
            max_results=min(ieee_quota, 20),  # 限制 IEEE 调用次数
            topic_id=topic.id,
        )
        
        return {
            "status": "ok",
            "inserted": len(inserted_ids),
            "new_count": new_count,
            "quota_used": 1,  # 记录 IEEE API 调用次数
        }
        
    except Exception as exc:
        logger.error("IEEE 抓取失败：%s", exc)
        return {"status": "failed", "error": str(exc), "inserted": 0}
```

**任务 3.2: IEEE 配额管理**

```python
# 文件：packages/storage/models.py
class IeeeApiQuota(Base):
    """IEEE API 配额追踪（新增表）"""
    
    __tablename__ = "ieee_api_quotas"
    
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    topic_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("topic_subscriptions.id"), nullable=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    api_calls_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    api_calls_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow
    )
    
    __table_args__ = (
        UniqueConstraint("topic_id", "date", name="uq_ieee_quota_daily"),
    )
```

---

#### 阶段四：前端适配（1 周）

**任务 4.1: 主题管理页面扩展**

前端需要添加：
1. **渠道选择组件**（多选框）
   - [x] ArXiv（免费）
   - [ ] IEEE Xplore（$129/月起）

2. **IEEE 配置面板**
   - IEEE API Key 输入框
   - 每日配额限制（默认 10 次/天）
   - 配额使用情况显示

3. **IEEE 论文特殊标识**
   - 列表页：IEEE 论文显示"IEEE"标签
   - PDF 阅读：提示"可能需要付费下载"

**任务 4.2: API 路由扩展**

```python
# 文件：apps/api/routers/topics.py
@router.post("/topics")
def create_topic(topic_data: TopicCreateExtended):
    """
    创建主题（支持多渠道）
    
    新增字段:
    - sources: list[str] = ["arxiv"]
    - ieee_daily_quota: int = 10
    - ieee_api_key_override: str | None
    """
    pass
```

---

## 四、实施风险与缓解

### 4.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| IEEE API 配额不足 | 🔴 高 | 高 | 实施严格的配额管理 + 优先级队列 |
| PDF 下载失败率高 | 🔴 高 | 中 | 明确提示用户"可能需要付费"，提供 arXiv 替代链接 |
| 去重不准确 | 🟡 中 | 中 | 实现 DOI + 标题 + 作者 多维度去重 |
| 数据迁移失败 | 🟡 中 | 高 | 先备份再迁移，支持回滚 |
| 性能下降 | 🟢 低 | 低 | IEEE 独立调度，不影响 ArXiv 流程 |

### 4.2 成本风险

**IEEE API 定价:**
- 免费版：50 次/天（功能受限）
- 基础版：$129/月（500 次/天）
- 专业版：$399/月（无限调用）

**成本控制策略:**
1. **每日硬限额**: 默认 10 次/天/主题，可手动调整
2. **配额告警**: 使用量达到 80% 时邮件通知
3. **智能降级**: 配额用尽时自动切换到 Semantic Scholar 免费 API
4. **ROI 评估**: 每月评估 IEEE 渠道使用率，决定是否续费

---

## 五、测试计划

### 5.1 单元测试

```python
# 文件：tests/test_ieee_client.py
def test_ieee_fetch_by_keywords():
    client = IeeeClient(api_key="test_key")
    papers = client.fetch_by_keywords("machine learning", max_results=5)
    assert len(papers) <= 5
    assert all(p.source == "ieee" for p in papers)

def test_ieee_paper_deduplication():
    # 测试 IEEE 论文去重逻辑
    pass
```

### 5.2 集成测试

1. **端到端测试**: 创建主题 → 配置 IEEE → 触发抓取 → 验证入库
2. **配额测试**: 验证 IEEE API 调用次数限制生效
3. **回滚测试**: 模拟 IEEE API 失败，验证不影响 ArXiv 流程

### 5.3 性能测试

- IEEE 并发请求压力测试（验证速率限制处理）
- 大批量论文去重性能（目标：<100ms/篇）

---

## 六、上线计划

### 6.1 灰度发布策略

**第 1 周**: 内部测试（仅开发团队可用）
- 部署到开发环境
- 团队内部主题配置 IEEE 渠道
- 监控 IEEE API 使用情况和成本

**第 2 周**: 小范围公测（10% 用户）
- 部署到生产环境（功能开关关闭）
- 邀请 10% 活跃用户参与测试
- 收集用户反馈，优化体验

**第 3 周**: 全量发布
- 功能开关全量打开
- 发送用户通知邮件
- 监控成本和性能指标

### 6.2 回滚方案

如果 IEEE 集成导致严重问题：
1. **立即关闭功能开关**
2. **恢复数据库备份**（如数据模型变更导致问题）
3. **保留已抓取的 IEEE 论文**（不影响现有数据）

---

## 七、成本效益分析

### 7.1 成本估算

**开发成本:**
- 后端开发：4 人周 × $2000/周 = $8000
- 前端开发：1 人周 × $2000/周 = $2000
- 测试：1 人周 × $1500/周 = $1500
- **总计**: $11,500

**运营成本:**
- IEEE API: $129/月（基础版）或 $399/月（专业版）
- 年度成本：$1,548 - $4,788

### 7.2 预期收益

**直接收益:**
- 论文覆盖率提升：+30%（IEEE 特有论文）
- 用户付费转化率：+5%（高级功能）

**间接收益:**
- 提升平台专业度
- 增强用户粘性
- 吸引更多科研用户

**ROI 评估:**
- 如果带来 10 个付费用户（$20/月），年收入 $2400
- 需要评估是否值得 $4000/年的 IEEE API 成本

---

## 八、结论与建议

### 8.1 老白的最终建议

**大白，听老白一句劝：**

1. **先别急着全量开发！** 建议分两步走：

   **第一步（MVP，1 周）:**
   - 只开发 IEEE 客户端和基础摄取逻辑
   - 支持手动触发 IEEE 搜索（不作为定时任务）
   - 不修改现有主题系统
   - 验证 IEEE API 的实际价值和成本
   
   **第二步（全量，4 周）:**
   - 如果 MVP 验证可行，再实施完整方案
   - 如果 ROI 不理想，及时止损

2. **成本控制是核心！**
   - IEEE API 配额必须严格限制
   - 给用户明确提示"IEEE 论文可能需要付费"
   - 优先使用 DOI 从 Semantic Scholar 获取免费元数据

3. **技术债务要还！**
   - `arxiv_id` 字段名确实太 SB 了，但为了向后兼容只能保留
   - 新代码必须用 `source` + `source_id`，不要再依赖 `arxiv_id`

### 8.2 决策建议

| 场景 | 建议 |
|------|------|
| **预算充足，追求论文覆盖率** | ✅ 立即实施完整方案 |
| **预算有限，想先验证价值** | ✅ 先做 MVP（1 周） |
| **用户反馈强烈需求 IEEE** | ✅ 优先实施 |
| **只是"有了更好"的需求** | ⚠️ 暂缓，先优化现有功能 |

---

## 附录

### A. IEEE API 文档

- 官方文档：https://developer.ieee.org/docs
- API 参考：https://ieeexploreapi.ieee.org/docs
- 示例代码：https://github.com/ieeecommunity/ieee-xplore-api-samples

### B. 相关文件清单

**需要修改的文件:**
```
packages/domain/schemas.py
packages/storage/models.py
packages/storage/repositories.py
packages/integrations/ieee_client.py (新建)
packages/integrations/channel_base.py (新建)
packages/integrations/arxiv_channel.py (新建)
packages/integrations/ieee_channel.py (新建)
packages/ai/pipelines.py
packages/ai/daily_runner.py
apps/api/routers/topics.py
apps/api/routers/papers.py
infra/migrations/versions/20260303_0009_add_ieee_channel.py (新建)
infra/migrations/versions/20260303_0010_add_topic_sources.py (新建)
```

**需要新增的文件:**
```
packages/integrations/ieee_client.py
packages/integrations/channel_base.py
packages/integrations/arxiv_channel.py
packages/integrations/ieee_channel.py
packages/integrations/__init__.py (修改导出)
```

### C. 环境变量配置

```bash
# .env.example 新增
IEEE_API_ENABLED=false
IEEE_API_KEY=your_ieee_api_key_here
IEEE_DAILY_QUOTA_DEFAULT=10  # 默认每日 IEEE API 限额
IEEE_PDF_DOWNLOAD_ENABLED=false  # 是否启用 PDF 下载（需要机构订阅）
```

---

**文档结束**

*老白备注：大白，这方案够详细了吧？有哪里不明白的随时问老白！*
