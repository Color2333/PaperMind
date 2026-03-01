"""
每日简报服务 - 精美日报生成
@author Bamzc
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from jinja2 import Template
from packages.config import get_settings
from packages.timezone import user_date_str

from packages.integrations.notifier import NotificationService
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository, AnalysisRepository
from sqlalchemy import select
from packages.storage.models import PaperTopic, TopicSubscription, AnalysisReport

logger = logging.getLogger(__name__)

# 状态标签映射
_STATUS_LABELS = {
    "unread": "未读",
    "skimmed": "已粗读",
    "deep_read": "已精读",
}


def _parse_deep_dive(md: str) -> dict:
    """解析 deep_dive_md 章节为字典"""
    if not md:
        return {}
    sections = {}
    current_key = None
    current_lines = []
    for line in md.split("\n"):
        if line.startswith("## "):
            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = line[3:].strip().lower()
            current_lines = []
        else:
            current_lines.append(line)
    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()
    return sections


DAILY_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 0 auto; padding: 24px; color: #1a1a2e; background: #fafbfc; }
  h1 { font-size: 24px; margin-bottom: 4px; }
  .subtitle { color: #666; font-size: 14px; margin-bottom: 24px; }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }
  .stat-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; text-align: center; }
  .stat-num { font-size: 28px; font-weight: 700; color: #6366f1; }
  .stat-label { font-size: 12px; color: #888; margin-top: 4px; }
  .section { margin-bottom: 28px; }
  .section-title { font-size: 18px; font-weight: 600; margin-bottom: 12px; padding-bottom: 6px; border-bottom: 2px solid #6366f1; }
  .rec-card, .paper-item, .deep-card { cursor: pointer; transition: box-shadow 0.15s; }
  .rec-card:hover, .paper-item:hover, .deep-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
  .rec-card { background: #f0f0ff; border-radius: 8px; padding: 14px; margin-bottom: 10px; }
  .rec-title { font-weight: 600; font-size: 14px; color: #1a1a2e; }
  .rec-meta { font-size: 12px; color: #888; margin-top: 4px; }
  .rec-reason { font-size: 13px; color: #555; margin-top: 6px; }
  .kw-tag { display: inline-block; background: #e8e8ff; color: #4f46e5; border-radius: 4px; padding: 3px 8px; font-size: 12px; margin: 2px; }
  .topic-group { margin-bottom: 20px; }
  .topic-name { font-size: 15px; font-weight: 600; color: #6366f1; margin-bottom: 8px; }
  .paper-item { background: #fff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; margin-bottom: 8px; }
  .paper-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
  .paper-title { font-weight: 600; font-size: 14px; }
  .paper-summary { font-size: 13px; color: #555; margin-top: 6px; }
  .paper-id { font-size: 11px; color: #aaa; }
  .ai-insight { background: #f0fdf4; border-left: 3px solid #22c55e; padding: 12px; margin: 10px 0; border-radius: 4px; }
  .ai-insight-title { font-weight: 600; color: #15803d; margin-bottom: 6px; }
  .btn { display: inline-block; padding: 6px 14px; background: #6366f1; color: #fff; text-decoration: none; border-radius: 4px; font-size: 12px; margin-top: 6px; }
  .footer { text-align: center; color: #aaa; font-size: 12px; margin-top: 40px; padding-top: 16px; border-top: 1px solid #e2e8f0; }
  a { color: #6366f1; text-decoration: none; }
  a:hover { text-decoration: underline; }
  
  /* Deep read cards */
  .deep-card { background: linear-gradient(135deg, #f8f7ff 0%, #f0f0ff 100%); border: 1px solid #c7c3f7; border-left: 4px solid #6366f1; border-radius: 10px; padding: 16px; margin-bottom: 14px; }
  .deep-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .deep-title { font-weight: 700; font-size: 15px; color: #1a1a2e; flex: 1; }
  .deep-section { margin-top: 10px; }
  .deep-section-label { font-size: 12px; font-weight: 600; color: #6366f1; margin-bottom: 4px; }
  .deep-text { font-size: 13px; color: #444; line-height: 1.6; margin: 0; }
  .risk-list { margin: 4px 0 0 16px; padding: 0; font-size: 12px; color: #b45309; }
  .risk-list li { margin-bottom: 2px; }
  
  /* Score badges */
  .score-badge { display: inline-flex; align-items: center; border-radius: 9999px; font-weight: 700; }
  .score-sm { font-size: 10px; padding: 1px 6px; }
  .score-high { background: #dcfce7; color: #15803d; }
  .score-mid { background: #fef3c7; color: #b45309; }
  .score-low { background: #fee2e2; color: #dc2626; }
  
  /* Deep badge */
  .deep-badge { display: inline; background: #ede9fe; color: #6366f1; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; }
  
  /* Innovation tags */
  .innovation-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
  .innovation-tag { display: inline-block; background: #fef3c7; color: #92400e; border-radius: 4px; padding: 2px 8px; font-size: 11px; }
</style>
</head>
<body>

<h1>🧠 PaperMind 研究日报</h1>
<div class="subtitle">{{ date }} · 由 AI 自动生成</div>

<div class="stats">
  <div class="stat-card">
    <div class="stat-num">{{ total_papers }}</div>
    <div class="stat-label">论文总量</div>
  </div>
  <div class="stat-card">
    <div class="stat-num">{{ today_new }}</div>
    <div class="stat-label">今日新增</div>
  </div>
  <div class="stat-card">
    <div class="stat-num">{{ week_new }}</div>
    <div class="stat-label">本周新增</div>
  </div>
  <div class="stat-card">
    <div class="stat-num">{{ deep_read_count }}</div>
    <div class="stat-label">已精读</div>
  </div>
</div>

{% if ai_summary %}
<div class="section">
  <div class="section-title">🤖 AI 今日洞察</div>
  <div class="ai-insight">
    <div class="ai-insight-title">核心发现</div>
    <p style="margin: 6px 0; font-size: 13px; line-height: 1.6;">{{ ai_summary }}</p>
  </div>
</div>
{% endif %}

{% if deep_read_highlights %}
<div class="section">
  <div class="section-title">🔬 精读精选</div>
  {% for d in deep_read_highlights %}
  <div class="deep-card" data-paper-id="{{ d.id }}">
    <div class="deep-header">
      <a href="{{ site_url }}/papers/{{ d.id }}" target="_blank" class="deep-title">{{ d.title }}</a>
      {% if d.skim_score %}
      <span class="score-badge {% if d.skim_score >= 0.8 %}score-high{% elif d.skim_score >= 0.6 %}score-mid{% else %}score-low{% endif %}">
        {{ "%.0f"|format(d.skim_score * 100) }}分
      </span>
      {% endif %}
    </div>
    <div class="paper-id">arXiv: {{ d.arxiv_id }}</div>
    {% if d.method %}
    <div class="deep-section">
      <div class="deep-section-label">📐 方法</div>
      <p class="deep-text">{{ d.method[:300] }}</p>
    </div>
    {% endif %}
    {% if d.experiments %}
    <div class="deep-section">
      <div class="deep-section-label">🧪 实验</div>
      <p class="deep-text">{{ d.experiments[:300] }}</p>
    </div>
    {% endif %}
    {% if d.risks %}
    <div class="deep-section">
      <div class="deep-section-label">⚠️ 审稿风险</div>
      <ul class="risk-list">
        {% for risk in d.risks[:3] %}
        <li>{{ risk }}</li>
        {% endfor %}
      </ul>
    </div>
    {% endif %}
    <a href="{{ site_url }}/papers/{{ d.id }}" class="btn" target="_blank">查看详情</a>
  </div>
  {% endfor %}
</div>
{% endif %}

{% if recommendations %}
<div class="section">
  <div class="section-title">🎯 AI 为你推荐</div>
  {% for r in recommendations %}
  <div class="rec-card" data-paper-id="{{ r.id }}" data-arxiv-id="{{ r.arxiv_id }}">
    <div class="rec-title">
      <a href="{{ site_url }}/papers/{{ r.id }}" target="_blank">{{ r.title }}</a>
    </div>
    <div class="rec-meta">arXiv: <a href="https://arxiv.org/abs/{{ r.arxiv_id }}" target="_blank">{{ r.arxiv_id }}</a> · 相似度：{{ "%.0f"|format(r.similarity * 100) }}%</div>
    {% if r.title_zh %}
    <div class="rec-reason">💡 {{ r.title_zh }}</div>
    {% endif %}
    <a href="{{ site_url }}/papers/{{ r.id }}" class="btn" target="_blank">查看详情</a>
  </div>
  {% endfor %}
</div>
{% endif %}

{% if hot_keywords %}
<div class="section">
  <div class="section-title">🔥 本周热点</div>
  <div>
    {% for kw in hot_keywords %}
    <span class="kw-tag">{{ kw.keyword }} ({{ kw.count }})</span>
    {% endfor %}
  </div>
</div>
{% endif %}

{% if topic_groups %}
<div class="section">
  <div class="section-title">📋 论文分类概览</div>
  {% for topic_name, papers in topic_groups.items() %}
  <div class="topic-group">
    <div class="topic-name">📁 {{ topic_name }}（{{ papers|length }}篇）</div>
    {% for p in papers %}
    <div class="paper-item" data-paper-id="{{ p.id }}" data-arxiv-id="{{ p.arxiv_id }}">
      <div class="paper-header">
        <div class="paper-title">
          <a href="{{ site_url }}/papers/{{ p.id }}" target="_blank">{{ p.title }}</a>
        </div>
        {% if p.skim_score %}
        <span class="score-badge score-sm {% if p.skim_score >= 0.8 %}score-high{% elif p.skim_score >= 0.6 %}score-mid{% else %}score-low{% endif %}">
          {{ "%.0f"|format(p.skim_score * 100) }}
        </span>
        {% endif %}
      </div>
      <div class="paper-id">arXiv: <a href="https://arxiv.org/abs/{{ p.arxiv_id }}" target="_blank">{{ p.arxiv_id }}</a> · {{ p.read_status }}{% if p.has_deep_read %} · <span class="deep-badge">已精读</span>{% endif %}</div>
      {% if p.innovations %}
      <div class="innovation-tags">
        {% for inn in p.innovations[:3] %}
        <span class="innovation-tag">💡 {{ inn[:60] }}</span>
        {% endfor %}
      </div>
      {% endif %}
      {% if p.summary %}
      <div class="paper-summary">{{ p.summary }}</div>
      {% endif %}
      <a href="{{ site_url }}/papers/{{ p.id }}" class="btn" target="_blank">阅读原文</a>
    </div>
    {% endfor %}
  </div>
  {% endfor %}
</div>
{% endif %}

{% if uncategorized %}
<div class="section">
  <div class="section-title">📄 其他论文</div>
  {% for p in uncategorized %}
  <div class="paper-item" data-paper-id="{{ p.id }}" data-arxiv-id="{{ p.arxiv_id }}">
    <div class="paper-header">
      <div class="paper-title">
        <a href="{{ site_url }}/papers/{{ p.id }}" target="_blank">{{ p.title }}</a>
      </div>
      {% if p.skim_score %}
      <span class="score-badge score-sm {% if p.skim_score >= 0.8 %}score-high{% elif p.skim_score >= 0.6 %}score-mid{% else %}score-low{% endif %}">
        {{ "%.0f"|format(p.skim_score * 100) }}
      </span>
      {% endif %}
    </div>
    <div class="paper-id">arXiv: <a href="https://arxiv.org/abs/{{ p.arxiv_id }}" target="_blank">{{ p.arxiv_id }}</a> · {{ p.read_status }}{% if p.has_deep_read %} · <span class="deep-badge">已精读</span>{% endif %}</div>
    {% if p.innovations %}
    <div class="innovation-tags">
      {% for inn in p.innovations[:3] %}
      <span class="innovation-tag">💡 {{ inn[:60] }}</span>
      {% endfor %}
    </div>
    {% endif %}
    {% if p.summary %}
    <div class="paper-summary">{{ p.summary }}</div>
    {% endif %}
    <a href="{{ site_url }}/papers/{{ p.id }}" class="btn" target="_blank">阅读原文</a>
  </div>
  {% endfor %}
</div>
{% endif %}

<div class="footer">
  PaperMind · AI 驱动的学术研究工作流平台<br>
  <a href="{{ site_url }}" target="_blank">{{ site_url }}</a>
</div>

</body>
</html>
""")


class DailyBriefService:
    def __init__(self) -> None:
        self.notifier = NotificationService()

    def build_html(self, limit: int = 30) -> str:
        from packages.ai.recommendation_service import (
            RecommendationService,
            TrendService,
        )
        from packages.config import get_settings

        settings = get_settings()

        # 并行获取推荐、热点、摘要、AI 分析
        trend_svc = TrendService()
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_rec = pool.submit(RecommendationService().recommend, top_k=5)
            f_hot = pool.submit(trend_svc.detect_hot_keywords, days=7, top_k=10)
            f_sum = pool.submit(trend_svc.get_today_summary)
            f_ai = pool.submit(self._generate_ai_summary, limit)
        recommendations = f_rec.result()
        hot_keywords = f_hot.result()
        summary = f_sum.result()
        ai_summary = f_ai.result()

        # 获取论文列表（按主题分组）
        with session_scope() as session:
            papers = PaperRepository(session).list_latest(limit=limit)
            paper_ids = [p.id for p in papers]
            summaries = AnalysisRepository(session).summaries_for_papers(paper_ids)

            # 获取所有分析reports（包含深读内容）
            analysis_q = select(AnalysisReport).where(AnalysisReport.paper_id.in_(paper_ids))
            analysis_reports = {r.paper_id: r for r in session.execute(analysis_q).scalars()}

            topic_rows = session.execute(
                select(PaperTopic.paper_id, TopicSubscription.name)
                .join(
                    TopicSubscription,
                    PaperTopic.topic_id == TopicSubscription.id,
                )
                .where(PaperTopic.paper_id.in_(paper_ids))
            ).all()

            topic_map: dict[str, list[str]] = {}
            for paper_id, topic_name in topic_rows:
                topic_map.setdefault(paper_id, []).append(topic_name)

            # 分离精读论文
            deep_read_papers = []
            for p in papers:
                report = analysis_reports.get(p.id)
                if report and report.deep_dive_md:
                    deep_read_papers.append((p, report))

            # 构建精读高亮
            deep_read_highlights = []
            for p, report in deep_read_papers[:5]:  # 取前 5 篇
                sections = _parse_deep_dive(report.deep_dive_md)
                deep_read_highlights.append(
                    {
                        "id": str(p.id),
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "skim_score": report.skim_score,
                        "method": sections.get("method", ""),
                        "experiments": sections.get("experiments", ""),
                        "risks": (report.key_insights or {}).get("reviewer_risks", []),
                    }
                )

            # 按主题分组
            topic_groups: dict[str, list[dict]] = defaultdict(list)
            uncategorized: list[dict] = []

            for p in papers:
                status_label = _STATUS_LABELS.get(p.read_status.value, p.read_status.value)
                report = analysis_reports.get(p.id)
                item = {
                    "id": str(p.id),
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "read_status": status_label,
                    "summary": (summaries.get(p.id, "") or "")[:400],
                    "skim_score": report.skim_score if report else None,
                    "innovations": (report.key_insights or {}).get("skim_innovations", [])
                    if report
                    else [],
                    "has_deep_read": bool(report and report.deep_dive_md),
                }
                topics = topic_map.get(p.id, [])
                if topics:
                    for t in topics:
                        topic_groups[t].append(item)
                else:
                    uncategorized.append(item)

        return DAILY_TEMPLATE.render(
            site_url=settings.site_url,
            date=user_date_str(),
            total_papers=summary["total_papers"],
            today_new=summary["today_new"],
            week_new=summary["week_new"],
            deep_read_count=len(deep_read_papers),
            ai_summary=ai_summary,
            recommendations=recommendations,
            hot_keywords=hot_keywords,
            deep_read_highlights=deep_read_highlights,
            topic_groups=dict(topic_groups),
            uncategorized=uncategorized,
        )

    def _generate_ai_summary(self, limit: int = 20) -> str:
        """生成 AI 驱动的今日洞察"""
        from packages.integrations.llm_client import LLMClient

        with session_scope() as session:
            papers = PaperRepository(session).list_latest(limit=limit)
            if not papers:
                return "今日暂无新论文"

            # 提取标题和摘要（前 15 篇）
            paper_info = []
            for p in papers[:15]:
                info = f"- {p.title}"
                if hasattr(p, "abstract") and p.abstract:
                    info += f"\n  摘要：{p.abstract[:150]}"
                paper_info.append(info)

            prompt = f"""请作为一位资深研究员，分析以下最新论文列表，用中文撰写今日研究简报的核心洞察（200-400 字）。

## 最新论文
{chr(10).join(paper_info)}

请按以下结构撰写：
1. **今日焦点**：最值得关注的 1-2 个研究方向
2. **技术亮点**：关键技术突破或方法创新
3. **趋势洞察**：这些论文反映的整体研究趋势
4. **建议关注**：推荐深入阅读的论文及原因
"""

            try:
                llm = LLMClient()
                result = llm.summarize_text(prompt, stage="daily_brief")
                return result.content[:600]
            except Exception as exc:
                logger.warning("AI summary generation failed: %s", exc)
                return f"今日新增 {len(papers)} 篇论文，涵盖多个研究方向"

    def publish(self, recipient: str | None = None) -> dict:
        """生成并发布日报：存 HTML 文件 + 写入 generated_content 表 + 可选发邮件"""
        from packages.storage.repositories import GeneratedContentRepository

        html = self.build_html()
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"daily_brief_{ts}.html"
        saved = self.notifier.save_brief_html(filename, html)
        sent = False
        if recipient:
            sent = self.notifier.send_email_html(recipient, "PaperMind Daily Brief", html)

        # 写入 generated_content 表，确保研究简报页面能查到
        content_id = None
        try:
            with session_scope() as session:
                repo = GeneratedContentRepository(session)
                gc = repo.create(
                    content_type="daily_brief",
                    title=f"Daily Brief: {user_date_str()}",
                    markdown=html,
                    metadata_json={
                        "saved_path": saved or "",
                        "email_sent": sent,
                        "source": "auto" if not recipient else "manual",
                    },
                )
                content_id = gc.id
        except Exception as exc:
            logger.warning("写入 generated_content 失败：%s", exc)

        return {"saved_path": saved, "email_sent": sent, "content_id": content_id}
