"""
每日简报服务 - 精美日报生成
@author Bamzc
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from jinja2 import Template
from packages.config import get_settings

from packages.integrations.notifier import NotificationService
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository, AnalysisRepository
from sqlalchemy import select
from packages.storage.models import PaperTopic, TopicSubscription
DAILY_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', \
sans-serif; max-width: 800px; margin: 0 auto; padding: 24px; \
color: #1a1a2e; background: #fafbfc; }
  h1 { font-size: 24px; margin-bottom: 4px; }
  .subtitle { color: #666; font-size: 14px; margin-bottom: 24px; }
  .stats { display: flex; gap: 16px; margin-bottom: 24px; }
  .stat-card { background: #fff; border: 1px solid #e2e8f0; \
border-radius: 8px; padding: 16px; flex: 1; text-align: center; }
  .stat-num { font-size: 28px; font-weight: 700; color: #6366f1; }
  .stat-label { font-size: 12px; color: #888; margin-top: 4px; }
  .section { margin-bottom: 28px; }
  .section-title { font-size: 18px; font-weight: 600; \
margin-bottom: 12px; padding-bottom: 6px; \
border-bottom: 2px solid #6366f1; }
  .rec-card, .paper-item { cursor: pointer; transition: box-shadow 0.15s; }
  .rec-card:hover, .paper-item:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
  .rec-card { background: #f0f0ff; border-radius: 8px; \
padding: 14px; margin-bottom: 10px; }
  .rec-title { font-weight: 600; font-size: 14px; color: #1a1a2e; }
  .rec-meta { font-size: 12px; color: #888; margin-top: 4px; }
  .rec-reason { font-size: 13px; color: #555; margin-top: 6px; }
  .kw-tag { display: inline-block; background: #e8e8ff; \
color: #4f46e5; border-radius: 4px; padding: 3px 8px; \
font-size: 12px; margin: 2px; }
  .topic-group { margin-bottom: 20px; }
  .topic-name { font-size: 15px; font-weight: 600; \
color: #6366f1; margin-bottom: 8px; }
  .paper-item { background: #fff; border: 1px solid #e2e8f0; \
border-radius: 6px; padding: 12px; margin-bottom: 8px; }
  .paper-title { font-weight: 600; font-size: 14px; }
  .paper-summary { font-size: 13px; color: #555; margin-top: 6px; }
  .paper-id { font-size: 11px; color: #aaa; }
  .ai-insight { background: #f0fdf4; border-left: 3px solid #22c55e; \
padding: 10px; margin: 10px 0; border-radius: 4px; }
  .ai-insight-title { font-weight: 600; color: #15803d; margin-bottom: 6px; }
  .btn { display: inline-block; padding: 6px 14px; background: #6366f1; \
color: #fff; text-decoration: none; border-radius: 4px; \
font-size: 12px; margin-top: 6px; }
  .footer { text-align: center; color: #aaa; \
font-size: 12px; margin-top: 40px; padding-top: 16px; \
border-top: 1px solid #e2e8f0; }
  a { color: #6366f1; text-decoration: none; }
  a:hover { text-decoration: underline; }
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

{% if recommendations %}
<div class="section">
  <div class="section-title">🎯 AI 为你推荐</div>
  {% for r in recommendations %}
  <div class="rec-card" data-paper-id="{{ r.id }}" data-arxiv-id="{{ r.arxiv_id }}">
    <div class="rec-title">
      <a href="{{ site_url }}/papers/{{ r.id }}" target="_blank">{{ r.title }}</a>
    </div>
    <div class="rec-meta">arXiv: <a href="https://arxiv.org/abs/{{ r.arxiv_id }}" target="_blank">{{ r.arxiv_id }}</a> · \
相似度：{{ "%.0f"|format(r.similarity * 100) }}%</div>
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
    <div class="topic-name">📁 {{ topic_name }} \
（{{ papers|length }} 篇）</div>
    {% for p in papers %}
    <div class="paper-item" data-paper-id="{{ p.id }}" data-arxiv-id="{{ p.arxiv_id }}">
      <div class="paper-title">
        <a href="{{ site_url }}/papers/{{ p.id }}" target="_blank">{{ p.title }}</a>
      </div>
      <div class="paper-id">arXiv: <a href="https://arxiv.org/abs/{{ p.arxiv_id }}" target="_blank">{{ p.arxiv_id }}</a> · \
{{ p.read_status }}</div>
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
    <div class="paper-title">
      <a href="{{ site_url }}/papers/{{ p.id }}" target="_blank">{{ p.title }}</a>
    </div>
    <div class="paper-id">arXiv: <a href="https://arxiv.org/abs/{{ p.arxiv_id }}" target="_blank">{{ p.arxiv_id }}</a> · \
{{ p.read_status }}</div>
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

_STATUS_LABELS = {
    "unread": "未读",
    "skimmed": "已粗读",
    "deep_read": "已精读",
}


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

            # 按主题分组
            topic_groups: dict[str, list[dict]] = defaultdict(list)
            uncategorized: list[dict] = []

            for p in papers:
                status_label = _STATUS_LABELS.get(p.read_status.value, p.read_status.value)
                item = {
                    "id": str(p.id),
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "read_status": status_label,
                    "summary": (summaries.get(p.id, "") or "")[:400],
                }
                topics = topic_map.get(p.id, [])
                if topics:
                    for t in topics:
                        topic_groups[t].append(item)
                else:
                    uncategorized.append(item)

        return DAILY_TEMPLATE.render(
            site_url=settings.site_url,
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
            total_papers=summary["total_papers"],
            today_new=summary["today_new"],
            week_new=summary["week_new"],
            ai_summary=ai_summary,
            recommendations=recommendations,
            hot_keywords=hot_keywords,
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

            # 提取标题和摘要
            paper_info = []
            for p in papers[:10]:  # 只分析前 10 篇
                info = f"- {p.title}"
                if hasattr(p, "abstract") and p.abstract:
                    info += f" ({p.abstract[:100]}...)"
                paper_info.append(info)

            prompt = f"""请分析以下最新论文列表，用简洁的中文总结今日研究趋势和核心发现（100-200 字）：

{chr(10).join(paper_info)}

请用以下格式：
1. 主要研究方向
2. 关键技术突破
3. 值得关注的论文"""

            try:
                llm = LLMClient()
                result = llm.complete(prompt, stage="daily_brief")
                return result.content[:500]
            except Exception as exc:
                logger.warning("AI summary generation failed: %s", exc)
                return f"今日新增 {len(papers)} 篇论文，涵盖多个研究方向"

        # 并行获取推荐、热点、摘要
        trend_svc = TrendService()
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_rec = pool.submit(RecommendationService().recommend, top_k=5)
            f_hot = pool.submit(trend_svc.detect_hot_keywords, days=7, top_k=10)
            f_sum = pool.submit(trend_svc.get_today_summary)
        recommendations = f_rec.result()
        hot_keywords = f_hot.result()
        summary = f_sum.result()

        # 获取论文列表（按主题分组）
        with session_scope() as session:
            papers = PaperRepository(session).list_latest(limit=limit)
            paper_ids = [p.id for p in papers]
            summaries = AnalysisRepository(session).summaries_for_papers(paper_ids)
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

            # 按主题分组
            topic_groups: dict[str, list[dict]] = defaultdict(list)
            uncategorized: list[dict] = []

            for p in papers:
                status_label = _STATUS_LABELS.get(p.read_status.value, p.read_status.value)
                item = {
                    "id": str(p.id),
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "read_status": status_label,
                    "summary": (summaries.get(p.id, "") or "")[:400],
                }
                topics = topic_map.get(p.id, [])
                if topics:
                    for t in topics:
                        topic_groups[t].append(item)
                else:
                    uncategorized.append(item)

        return DAILY_TEMPLATE.render(
            date=datetime.now(UTC).strftime("%Y-%m-%d"),
            total_papers=summary["total_papers"],
            today_new=summary["today_new"],
            week_new=summary["week_new"],
            recommendations=recommendations,
            hot_keywords=hot_keywords,
            topic_groups=dict(topic_groups),
            uncategorized=uncategorized,
        )

    def publish(self, recipient: str | None = None) -> dict:
        html = self.build_html()
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"daily_brief_{ts}.html"
        saved = self.notifier.save_brief_html(filename, html)
        sent = False
        if recipient:
            sent = self.notifier.send_email_html(recipient, "PaperMind Daily Brief", html)
        return {"saved_path": saved, "email_sent": sent}
