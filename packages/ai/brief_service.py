"""
每日简报服务 - 精美日报生成
@author Color2333
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from jinja2 import Template
from sqlalchemy import select

from packages.config import get_settings
from packages.integrations.notifier import NotificationService
from packages.storage.db import session_scope
from packages.storage.models import AnalysisReport, PaperTopic, TopicSubscription
from packages.storage.repositories import AnalysisRepository, PaperRepository
from packages.timezone import user_date_str

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
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 0 auto; padding: 24px; color: #1a1a2e; background: linear-gradient(180deg, #fafbfc 0%, #f5f7ff 100%); }
  h1 { font-size: 26px; font-weight: 800; margin-bottom: 4px; background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
  .subtitle { color: #666; font-size: 14px; margin-bottom: 28px; display: flex; align-items: center; gap: 6px; }
  .subtitle::before { content: "📅"; }
  .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 32px; }
  .stat-card { background: linear-gradient(135deg, #fff 0%, #f8f9ff 100%); border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px; text-align: center; transition: transform 0.2s, box-shadow 0.2s; }
  .stat-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(99, 102, 241, 0.1); }
  .stat-num { font-size: 32px; font-weight: 800; background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; line-height: 1.2; }
  .stat-label { font-size: 12px; color: #888; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }
  .section { margin-bottom: 32px; }
  .section-title { font-size: 18px; font-weight: 700; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #e2e8f0; display: flex; align-items: center; gap: 8px; }
  .section-title::before { content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 2px; background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); }
  
  /* ===== 焦点区域 - 最高优先级 ===== */
  .focus-zone { background: linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 100%); border: 2px solid #22c55e; border-radius: 16px; padding: 20px; margin-bottom: 32px; }
  .focus-title { font-size: 20px; font-weight: 800; color: #15803d; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
  .focus-title::before { content: "🎯"; font-size: 24px; }
  
  /* AI 洞察增强 */
  .ai-insight-box { background: #fff; border-radius: 12px; padding: 18px; border-left: 4px solid #22c55e; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
  .ai-insight-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
  .ai-insight-icon { font-size: 20px; }
  .ai-insight-title { font-weight: 700; color: #15803d; font-size: 15px; }
  .ai-insight-content { font-size: 14px; line-height: 1.8; color: #374151; }
  
  /* 精读精选卡片增强 */
  .deep-card { background: linear-gradient(135deg, #faf5ff 0%, #f3e8ff 100%); border: 2px solid #c084fc; border-left: 4px solid #a855f7; border-radius: 14px; padding: 18px; margin-bottom: 16px; transition: all 0.2s; cursor: pointer; }
  .deep-card:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(168, 85, 247, 0.15); border-color: #a855f7; }
  .deep-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
  .deep-title { font-weight: 700; font-size: 16px; color: #1a1a2e; flex: 1; line-height: 1.4; }
  .deep-section { margin-top: 12px; }
  .deep-section-label { font-size: 12px; font-weight: 700; color: #7c3aed; margin-bottom: 6px; display: flex; align-items: center; gap: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
  .deep-text { font-size: 13px; color: #4b5563; line-height: 1.7; margin: 0; }
  .risk-list { margin: 6px 0 0 18px; padding: 0; font-size: 12px; color: #b45309; }
  .risk-list li { margin-bottom: 4px; line-height: 1.5; }
  
  /* 推荐卡片 */
  .rec-card { background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%); border: 1px solid #93c5fd; border-left: 3px solid #3b82f6; border-radius: 12px; padding: 16px; margin-bottom: 12px; transition: all 0.2s; cursor: pointer; }
  .rec-card:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(59, 130, 246, 0.15); border-color: #3b82f6; }
  .rec-title { font-weight: 600; font-size: 15px; color: #1a1a2e; line-height: 1.4; }
  .rec-meta { font-size: 12px; color: #6b7280; margin-top: 6px; display: flex; align-items: center; gap: 4px; }
  .rec-reason { font-size: 13px; color: #4b5563; margin-top: 8px; line-height: 1.6; font-style: italic; }
  
  /* 热点标签增强 */
  .kw-tag { display: inline-flex !important; align-items: center; gap: 4px; background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); color: #92400e; border-radius: 9999px; padding: 6px 14px !important; font-size: 13px !important; font-weight: 600; margin: 4px !important; border: 1px solid #f59e0b; transition: transform 0.2s; }
  .kw-tag:hover { transform: scale(1.05); }
  .kw-tag::before { content: "🔥"; font-size: 12px; }
  
  /* 主题分组 */
  .topic-group { margin-bottom: 24px; background: #fff; border-radius: 12px; padding: 16px; border: 1px solid #e2e8f0; }
  .topic-name { font-size: 16px; font-weight: 700; color: #6366f1; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; padding-bottom: 8px; border-bottom: 1px dashed #e2e8f0; }
  .topic-name::before { content: "📁"; font-size: 16px; }
  
  /* 普通论文卡片 */
  .paper-item { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; margin-bottom: 10px; transition: all 0.2s; cursor: pointer; }
  .paper-item:hover { border-color: #a5b4fc; box-shadow: 0 2px 8px rgba(99, 102, 241, 0.08); transform: translateY(-1px); }
  .paper-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
  .paper-title { font-weight: 600; font-size: 14px; color: #1a1a2e; line-height: 1.4; }
  .paper-summary { font-size: 13px; color: #6b7280; margin-top: 8px; line-height: 1.6; max-height: 60px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; transition: max-height 0.3s; }
  .paper-item:hover .paper-summary { max-height: 200px; }
  .paper-id { font-size: 11px; color: #9ca3af; font-family: ui-monospace, monospace; }
  
  /* 按钮增强 */
  .btn { display: inline-block; padding: 8px 16px; background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: #fff !important; text-decoration: none; border-radius: 8px; font-size: 12px; font-weight: 600; margin-top: 8px; transition: all 0.2s; border: none; cursor: pointer; }
  .btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3); }
  
  /* 分数徽章增强 */
  .score-badge { display: inline-flex !important; align-items: center; justify-content: center; border-radius: 9999px !important; font-weight: 800 !important; font-size: 11px !important; padding: 3px 8px !important; min-width: 48px; }
  .score-high { background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%) !important; color: #166534 !important; border: 1px solid #22c55e !important; }
  .score-mid { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%) !important; color: #92400e !important; border: 1px solid #f59e0b !important; }
  .score-low { background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%) !important; color: #991b1b !important; border: 1px solid #ef4444 !important; }
  
  /* 深度徽章 */
  .deep-badge { display: inline-flex !important; align-items: center; gap: 2px; background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%) !important; color: #6d28d9 !important; padding: 2px 8px !important; border-radius: 6px !important; font-size: 10px !important; font-weight: 700 !important; border: 1px solid #a855f7 !important; }
  .deep-badge::before { content: "✨"; font-size: 8px; }
  
  /* 创新标签增强 */
  .innovation-tags { display: flex !important; flex-wrap: wrap !important; gap: 6px !important; margin-top: 8px !important; }
  .innovation-tag { display: inline-flex !important; align-items: center; gap: 4px; background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%) !important; color: #78350f !important; border-radius: 8px !important; padding: 4px 10px !important; font-size: 11px !important; font-weight: 600 !important; border: 1px solid #f59e0b !important; }
  .innovation-tag::before { content: "💡"; font-size: 10px; }
  
  /* 页脚 */
  .footer { text-align: center; color: #9ca3af; font-size: 12px; margin-top: 48px; padding-top: 20px; border-top: 2px solid #e2e8f0; }
  .footer a { color: #6366f1; text-decoration: none; font-weight: 600; }
  .footer a:hover { text-decoration: underline; }
  
  a { color: #6366f1; text-decoration: none; transition: color 0.2s; }
  a:hover { color: #4f46e5; }
</style>
</head>
<body>

<h1>PaperMind 研究日报</h1>
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

{% if ai_summary or deep_read_highlights %}
<div class="focus-zone">
  <div class="focus-title">今日焦点</div>
  
  {% if ai_summary %}
  <div class="ai-insight-box">
    <div class="ai-insight-header">
      <span class="ai-insight-icon">🤖</span>
      <span class="ai-insight-title">AI 核心洞察</span>
    </div>
    <div class="ai-insight-content">{{ ai_summary }}</div>
  </div>
  {% endif %}
  
  {% if deep_read_highlights %}
  <div style="margin-top: 20px;">
    <div class="section-title" style="font-size: 16px; border-bottom: 1px dashed #c084fc;">
      🔬 精读精选 ({{ deep_read_highlights|length }}篇)
    </div>
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
      <div class="paper-id">arXiv: <a href="https://arxiv.org/abs/{{ d.arxiv_id }}" target="_blank">{{ d.arxiv_id }}</a></div>
      {% if d.method %}
      <div class="deep-section">
        <div class="deep-section-label">📐 方法</div>
        <p class="deep-text">{{ d.method[:280] }}{% if d.method|length > 280 %}...{% endif %}</p>
      </div>
      {% endif %}
      {% if d.experiments %}
      <div class="deep-section">
        <div class="deep-section-label">🧪 实验</div>
        <p class="deep-text">{{ d.experiments[:280] }}{% if d.experiments|length > 280 %}...{% endif %}</p>
      </div>
      {% endif %}
      {% if d.risks %}
      <div class="deep-section">
        <div class="deep-section-label">⚠️ 风险</div>
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
</div>
{% endif %}

{% if recommendations %}
<div class="section">
  <div class="section-title">💡 AI 为你推荐</div>
  {% for r in recommendations %}
  <div class="rec-card" data-paper-id="{{ r.id }}" data-arxiv-id="{{ r.arxiv_id }}">
    <div class="rec-title">
      <a href="{{ site_url }}/papers/{{ r.id }}" target="_blank">{{ r.title }}</a>
    </div>
    <div class="rec-meta">
      <span>arXiv: <a href="https://arxiv.org/abs/{{ r.arxiv_id }}" target="_blank">{{ r.arxiv_id }}</a></span>
      <span>·</span>
      <span class="score-badge score-high">{{ "%.0f"|format(r.similarity * 100) }}% 匹配</span>
    </div>
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
    <span class="kw-tag">{{ kw.keyword }} <span style="opacity: 0.7;">({{ kw.count }})</span></span>
    {% endfor %}
  </div>
</div>
{% endif %}

{% if topic_groups %}
<div class="section">
  <div class="section-title">📋 论文分类概览</div>
  {% for topic_name, papers in topic_groups.items() %}
  <div class="topic-group">
    <div class="topic-name">{{ topic_name }} ({{ papers|length }}篇)</div>
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
        <span class="innovation-tag">{{ inn[:50] }}</span>
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
      <span class="innovation-tag">{{ inn[:50] }}</span>
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

        # 如果没有指定收件人，从数据库读取配置
        if not recipient:
            from packages.storage.db import session_scope
            from packages.storage.repositories import DailyReportConfigRepository

            with session_scope() as session:
                config = DailyReportConfigRepository(session).get_config()
                if config.send_email_report and config.recipient_emails:
                    recipient = config.recipient_emails.split(",")[0]  # 取第一个收件人

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
