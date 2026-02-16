from __future__ import annotations

from datetime import UTC, datetime

from jinja2 import Template
from sqlalchemy import select

from packages.integrations.notifier import NotificationService
from packages.storage.db import session_scope
from packages.storage.models import PaperTopic, TopicSubscription
from packages.storage.repositories import (
    AnalysisRepository,
    PaperRepository,
)

DAILY_TEMPLATE = Template(
    """
    <html>
      <body>
        <h2>PaperMind Daily Brief - {{ date }}</h2>
        <ul>
        {% for p in papers %}
          <li>
            <strong>{{ p.title }}</strong><br />
            arXiv: {{ p.arxiv_id }}<br />
            状态: {{ p.read_status.value }}<br />
            主题: {{ p.topics }}<br />
            摘要: {{ p.summary }}
          </li>
        {% endfor %}
        </ul>
      </body>
    </html>
    """
)


class DailyBriefService:
    def __init__(self) -> None:
        self.notifier = NotificationService()

    def build_html(self, limit: int = 20) -> str:
        with session_scope() as session:
            papers = PaperRepository(session).list_latest(limit=limit)
            paper_ids = [p.id for p in papers]
            summaries = AnalysisRepository(session).summaries_for_papers(paper_ids)
            topic_rows = session.execute(
                select(PaperTopic.paper_id, TopicSubscription.name)
                .join(TopicSubscription, PaperTopic.topic_id == TopicSubscription.id)
                .where(PaperTopic.paper_id.in_(paper_ids))
            ).all()
            topic_map: dict[str, list[str]] = {}
            for paper_id, topic_name in topic_rows:
                topic_map.setdefault(paper_id, []).append(topic_name)
            view_data = []
            for p in papers:
                view_data.append(
                    {
                        "title": p.title,
                        "arxiv_id": p.arxiv_id,
                        "read_status": p.read_status,
                        "topics": ", ".join(topic_map.get(p.id, [])) or "未分配",
                        "summary": (summaries.get(p.id, "") or "暂无粗读摘要")[:320],
                    }
                )
            return DAILY_TEMPLATE.render(
                date=datetime.now(UTC).strftime("%Y-%m-%d"),
                papers=view_data,
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
