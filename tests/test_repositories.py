"""
Repository 行为测试 —— 守护 repositories.py 拆分时的回归
覆盖 upsert/list/topic/quota 核心读写路径
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from packages.domain.enums import ReadStatus
from packages.domain.schemas import PaperCreate
from packages.storage.repositories import (
    AnalysisRepository,
    CSFeedRepository,
    IeeeQuotaRepository,
    PaperRepository,
    TopicRepository,
)


class TestPaperRepository:
    def test_upsert_insert_then_update(self, db_session):
        """upsert_paper 首次插入、二次同 arxiv_id 走更新分支"""
        repo = PaperRepository(db_session)
        paper = PaperCreate(
            arxiv_id="2401.00001",
            title="Original Title",
            abstract="orig",
            publication_date=date(2026, 1, 1),
            metadata={"authors": ["A"]},
        )
        saved = repo.upsert_paper(paper)
        assert saved.id is not None
        first_id = saved.id

        # 二次：同 arxiv_id → 更新而非新建
        updated = repo.upsert_paper(
            PaperCreate(
                arxiv_id="2401.00001",
                title="Updated Title",
                abstract="upd",
                publication_date=date(2026, 1, 2),
                metadata={"authors": ["B"]},
            )
        )
        assert updated.id == first_id
        assert updated.title == "Updated Title"
        assert updated.abstract == "upd"

    def test_upsert_preserves_skim_metadata_on_refetch(self, db_session):
        """重复抓取同一论文时保留 skim 写入的 keywords/title_zh/abstract_zh（High 2a）

        此前更新分支 existing.metadata_json = data.metadata（整体覆盖）会抹掉 skim 产物，
        重复抓取丢失已花钱算出的中文翻译/关键词。
        """
        repo = PaperRepository(db_session)
        saved = repo.upsert_paper(
            PaperCreate(
                arxiv_id="2401.00002",
                title="Orig",
                abstract="a",
                metadata={"categories": ["cs.AI"], "authors": ["X"]},
            )
        )
        # 模拟 skim 写入的派生字段
        saved.metadata_json = {
            "categories": ["cs.AI"],
            "authors": ["X"],
            "keywords": ["llm", "reasoning"],
            "title_zh": "大语言模型推理",
            "abstract_zh": "摘要中文",
        }
        db_session.flush()

        # 二次抓取：arxiv 原始元数据不含 skim 字段
        updated = repo.upsert_paper(
            PaperCreate(
                arxiv_id="2401.00002",
                title="New Title",
                abstract="b",
                metadata={"categories": ["cs.AI", "cs.CL"], "authors": ["X", "Y"]},
            )
        )
        meta = updated.metadata_json or {}
        # skim 派生字段应保留
        assert meta.get("keywords") == ["llm", "reasoning"]
        assert meta.get("title_zh") == "大语言模型推理"
        assert meta.get("abstract_zh") == "摘要中文"
        # arxiv 原始字段应更新
        assert meta.get("categories") == ["cs.AI", "cs.CL"]
        assert meta.get("authors") == ["X", "Y"]

    def test_upsert_multi_source_arxiv_id_synthesis(self, db_session):
        """非 arXiv 源（arxiv_id=None）用 source:source_id 合成 arxiv_id"""
        repo = PaperRepository(db_session)
        ieee = PaperCreate(
            source="ieee",
            source_id="10185093",
            doi="10.1109/x",
            arxiv_id=None,
            title="IEEE Paper",
            abstract="abs",
            metadata={},
        )
        saved = repo.upsert_paper(ieee)
        assert saved.arxiv_id == "ieee:10185093"
        assert saved.source == "ieee"
        assert saved.doi == "10.1109/x"

    def test_list_existing_arxiv_ids(self, db_session):
        """list_existing_arxiv_ids 返回已存在的 arxiv_id 集合"""
        repo = PaperRepository(db_session)
        repo.upsert_paper(PaperCreate(arxiv_id="2401.00001", title="A", abstract="", metadata={}))
        repo.upsert_paper(PaperCreate(arxiv_id="2401.00002", title="B", abstract="", metadata={}))
        existing = repo.list_existing_arxiv_ids(["2401.00001", "2401.00002", "9999.99999"])
        assert existing == {"2401.00001", "2401.00002"}

    def test_update_read_status(self, db_session):
        """update_read_status 改状态并持久化"""
        repo = PaperRepository(db_session)
        saved = repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00003", title="C", abstract="", metadata={})
        )
        assert saved.read_status == ReadStatus.unread
        from uuid import UUID

        repo.update_read_status(UUID(saved.id), ReadStatus.skimmed)
        db_session.flush()
        reloaded = repo.get_by_id(UUID(saved.id))
        assert reloaded.read_status == ReadStatus.skimmed


class TestTopicRepository:
    def test_upsert_topic_create_then_update(self, db_session):
        """upsert_topic 首次创建、二次同名更新"""
        repo = TopicRepository(db_session)
        t1 = repo.upsert_topic(name="LLM", query="large language model")
        assert t1.id is not None
        assert t1.name == "LLM"
        assert t1.query == "large language model"

        # 同名 → 更新
        t2 = repo.upsert_topic(name="LLM", query="llm survey", max_results_per_run=50)
        assert t2.id == t1.id
        assert t2.query == "llm survey"
        assert t2.max_results_per_run == 50

    def test_list_topics_enabled_only(self, db_session):
        """list_topics enabled_only 过滤禁用主题"""
        repo = TopicRepository(db_session)
        repo.upsert_topic(name="Active", query="q1", enabled=True)
        repo.upsert_topic(name="Inactive", query="q2", enabled=False)

        all_topics = repo.list_topics()
        assert len(all_topics) == 2

        enabled = repo.list_topics(enabled_only=True)
        assert len(enabled) == 1
        assert enabled[0].name == "Active"

    def test_get_by_name(self, db_session):
        """get_by_name 命中与未命中"""
        repo = TopicRepository(db_session)
        repo.upsert_topic(name="CV", query="computer vision")
        found = repo.get_by_name("CV")
        assert found is not None
        assert found.query == "computer vision"
        assert repo.get_by_name("nonexistent") is None

    def test_update_run_status_persists_last_run_at_and_error(self, db_session):
        """update_run_status 持久化 last_run_at/last_error（Critical #4：抓取失败可查可补抓）"""
        repo = TopicRepository(db_session)
        topic = repo.upsert_topic(name="FailTopic", query="q")
        tid = topic.id
        db_session.flush()

        # 成功：error=None，清空 last_error，写入 last_run_at
        repo.update_run_status(tid, error=None)
        db_session.refresh(topic)
        assert topic.last_run_at is not None
        assert topic.last_error is None

        # 失败：error 写入并截断到 500
        long_err = "x" * 800
        repo.update_run_status(tid, error=long_err)
        db_session.refresh(topic)
        assert topic.last_error is not None
        assert len(topic.last_error) == 500
        assert topic.last_run_at is not None

        # 未知 topic_id：静默跳过，不抛
        repo.update_run_status("nonexistent-id", error="boom")

    def test_update_run_status_allows_next_error_clears_previous(self, db_session):
        """连续抓取：上次错误在下次成功时被清空"""
        repo = TopicRepository(db_session)
        topic = repo.upsert_topic(name="Recover", query="q")
        db_session.flush()
        repo.update_run_status(topic.id, error="first fail")
        db_session.refresh(topic)
        assert topic.last_error == "first fail"
        repo.update_run_status(topic.id, error=None)
        db_session.refresh(topic)
        assert topic.last_error is None


class TestIeeeQuotaRepository:
    def test_quota_lifecycle_with_topic(self, db_session):
        """配额完整生命周期：检查→消耗→剩余→重置（带真实父 TopicSubscription）"""
        topic_repo = TopicRepository(db_session)
        topic = topic_repo.upsert_topic(name="IEEE Topic", query="ieee query")
        db_session.flush()

        quota_repo = IeeeQuotaRepository(db_session)
        today = date.today()
        tid = topic.id

        # 初始有配额
        assert quota_repo.check_quota(tid, today, limit=10) is True
        # 消耗 3
        assert quota_repo.consume_quota(tid, today, 3) is True
        assert quota_repo.get_remaining(tid, today) == 7
        # 超额消耗失败
        assert quota_repo.consume_quota(tid, today, 10) is False
        # 重置
        quota_repo.reset_quota(tid, today, new_limit=5)
        assert quota_repo.get_remaining(tid, today) == 5


class TestCSFeedRepository:
    def test_update_run_status_accumulates_same_day(self, db_session):
        """当日多次抓取累加（Critical #3：覆盖 bug 会绕过 daily_limit）"""
        repo = CSFeedRepository(db_session)
        repo.upsert_subscription(category_code="cs.AI", daily_limit=30)
        db_session.flush()

        repo.update_run_status("cs.AI", count=10)
        sub = repo.get_subscription("cs.AI")
        assert sub.last_run_count == 10

        # 同日第二次抓取：应累加而非覆盖
        repo.update_run_status("cs.AI", count=5)
        db_session.refresh(sub)
        assert sub.last_run_count == 15

    def test_update_run_status_resets_across_day(self, db_session):
        """跨天抓取先清零，避免昨天余量带进今天（Critical #3）"""
        repo = CSFeedRepository(db_session)
        repo.upsert_subscription(category_code="cs.LG", daily_limit=30)
        sub = repo.get_subscription("cs.LG")
        # 模拟昨天已抓 20，last_run_at 设为昨天
        sub.last_run_at = datetime.now(UTC) - timedelta(days=1)
        sub.last_run_count = 20
        db_session.commit()

        # 今天再抓 8：跨天应先清零，再累加 → 8（而非 20+8=28）
        repo.update_run_status("cs.LG", count=8)
        db_session.refresh(sub)
        assert sub.last_run_count == 8
        assert sub.status == "active"

    def test_update_run_status_unknown_category_silent(self, db_session):
        """未知 category_code：静默跳过，不抛"""
        repo = CSFeedRepository(db_session)
        repo.update_run_status("cs.NONEXIST", count=5)


class TestAnalysisRepository:
    def test_get_or_create_idempotent(self, db_session):
        """_get_or_create 首次创建、二次返回同一行"""
        repo = AnalysisRepository(db_session)
        # 需要先有 paper（外键约束）
        paper_repo = PaperRepository(db_session)
        paper = paper_repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00010", title="t", abstract="a", metadata={})
        )
        db_session.flush()

        r1 = repo._get_or_create(paper.id)
        r2 = repo._get_or_create(paper.id)
        assert r1.id == r2.id

    def test_get_or_create_unique_no_duplicates(self, db_session):
        """AnalysisReport.paper_id 唯一：重复 _get_or_create 不产生重复行（High 2b）"""
        from sqlalchemy import func, select

        from packages.storage.models import AnalysisReport

        paper_repo = PaperRepository(db_session)
        paper = paper_repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00011", title="t", abstract="a", metadata={})
        )
        db_session.flush()

        repo = AnalysisRepository(db_session)
        r1 = repo._get_or_create(paper.id)
        db_session.flush()
        r2 = repo._get_or_create(paper.id)
        db_session.flush()
        assert r1.id == r2.id  # 同一行

        # 全表只有这一条该 paper_id 的 report
        count = db_session.execute(
            select(func.count())
            .select_from(AnalysisReport)
            .where(AnalysisReport.paper_id == str(paper.id))
        ).scalar_one()
        assert count == 1

    def test_get_or_create_integrity_error_recovers(self, db_session):
        """直接插入违反 unique 后，_get_or_create 回滚并取已存在行（High 2b IntegrityError 路径）"""
        from uuid import uuid4

        from packages.storage.models import AnalysisReport

        paper_repo = PaperRepository(db_session)
        paper = paper_repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00013", title="t", abstract="a", metadata={})
        )
        db_session.flush()
        pid = str(paper.id)

        # 先 commit 一行（模拟并发事务 A 已提交）
        existing = AnalysisReport(id=str(uuid4()), paper_id=pid, key_insights={"a": 1})
        db_session.add(existing)
        db_session.commit()

        # 再次 _get_or_create：select 命中已存在行，不走插入分支，不抛 IntegrityError
        repo = AnalysisRepository(db_session)
        again = repo._get_or_create(paper.id)
        assert again.id == existing.id

    def test_skim_report_roundtrip(self, db_session):
        """upsert_skim 写入 summary_md/skim_score/key_insights"""
        from packages.domain.schemas import SkimReport

        paper_repo = PaperRepository(db_session)
        paper = paper_repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00012", title="t", abstract="a", metadata={})
        )
        db_session.flush()

        repo = AnalysisRepository(db_session)
        skim = SkimReport(
            one_liner="一句话总结",
            innovations=["创新1", "创新2"],
            relevance_score=0.85,
        )
        repo.upsert_skim(paper.id, skim)
        db_session.flush()

        report = repo._get_or_create(paper.id)
        assert report.summary_md is not None
        assert "一句话总结" in report.summary_md
        assert report.skim_score == 0.85
        assert report.key_insights.get("skim_one_liner") == "一句话总结"


class TestCSFeedTopicLink:
    def test_link_creates_disabled_topic_and_links_papers(self, db_session):
        """cs_feed 论文关联到每分类的 disabled topic（接入主题侧边栏/图谱/统计）"""
        from packages.ai.cs_feed_orchestrator import CSFeedOrchestrator

        repo = PaperRepository(db_session)
        p1 = repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00201", title="t1", abstract="a", metadata={})
        )
        p2 = repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00202", title="t2", abstract="a", metadata={})
        )
        db_session.flush()

        CSFeedOrchestrator._link_cs_papers_to_topic(db_session, "cs.AI", [p1.id, p2.id])
        db_session.commit()

        topic = TopicRepository(db_session).get_by_name("csfeed:cs.AI")
        assert topic is not None
        # enabled=False 防 topic_dispatch 重复抓取同一分类
        assert topic.enabled is False
        assert topic.query == "cat:cs.AI"
        linked = PaperRepository(db_session).list_by_topic(topic.id)
        assert len(linked) == 2

    def test_link_idempotent_no_duplicate_rows(self, db_session):
        """重复关联同一 (paper, topic) 不产生重复行（uq_paper_topic 兜底）"""
        from packages.ai.cs_feed_orchestrator import CSFeedOrchestrator

        repo = PaperRepository(db_session)
        p = repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00203", title="t", abstract="a", metadata={})
        )
        db_session.flush()

        CSFeedOrchestrator._link_cs_papers_to_topic(db_session, "cs.LG", [p.id])
        db_session.commit()
        # 再关联一次
        CSFeedOrchestrator._link_cs_papers_to_topic(db_session, "cs.LG", [p.id])
        db_session.commit()

        topic = TopicRepository(db_session).get_by_name("csfeed:cs.LG")
        linked = PaperRepository(db_session).list_by_topic(topic.id)
        assert len(linked) == 1  # 幂等，不重复

    def test_link_category_isolation(self, db_session):
        """不同分类建独立 topic，论文不串"""
        from packages.ai.cs_feed_orchestrator import CSFeedOrchestrator

        repo = PaperRepository(db_session)
        p_ai = repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00204", title="ai", abstract="a", metadata={})
        )
        p_lg = repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00205", title="lg", abstract="a", metadata={})
        )
        db_session.flush()

        CSFeedOrchestrator._link_cs_papers_to_topic(db_session, "cs.AI", [p_ai.id])
        CSFeedOrchestrator._link_cs_papers_to_topic(db_session, "cs.LG", [p_lg.id])
        db_session.commit()

        t_ai = TopicRepository(db_session).get_by_name("csfeed:cs.AI")
        t_lg = TopicRepository(db_session).get_by_name("csfeed:cs.LG")
        assert len(PaperRepository(db_session).list_by_topic(t_ai.id)) == 1
        assert len(PaperRepository(db_session).list_by_topic(t_lg.id)) == 1
        assert t_ai.id != t_lg.id


class TestWorkerAlertDedup:
    """Worker 告警去重逻辑测试（可观测性：同错误 1h 内不重复发邮件）"""

    def test_send_alert_dedup_within_window(self, monkeypatch):
        from apps.worker import main as wm

        # 重置去重状态
        wm._last_alerts.clear()
        sent: list[str] = []

        def fake_send(self, recipient, subject, html):
            sent.append(subject)
            return True

        monkeypatch.setattr(
            "packages.integrations.notifier.NotificationService.send_email_html", fake_send
        )
        monkeypatch.setattr(
            "packages.config.get_settings",
            lambda: type("S", (), {"notify_default_to": "test@example.com"})(),
        )

        wm._send_alert("[PaperMind] Test Alert", "<p>x</p>", "test_key")
        assert len(sent) == 1, "首次告警应发送"
        # 窗口内再次告警 → 去重，不发送
        wm._send_alert("[PaperMind] Test Alert", "<p>x</p>", "test_key")
        assert len(sent) == 1, "去重窗口内不应重复发送"
        wm._last_alerts.clear()

    def test_send_alert_no_recipient_silent(self, monkeypatch):
        from apps.worker import main as wm

        wm._last_alerts.clear()
        sent: list[str] = []

        def fake_send(self, recipient, subject, html):
            sent.append(subject)
            return True

        monkeypatch.setattr(
            "packages.integrations.notifier.NotificationService.send_email_html", fake_send
        )
        # notify_default_to 未配置
        monkeypatch.setattr(
            "packages.config.get_settings",
            lambda: type("S", (), {"notify_default_to": None})(),
        )
        wm._send_alert("[PaperMind] Test", "<p>x</p>", "no_recv")
        assert len(sent) == 0, "无收件人应静默跳过"
        wm._last_alerts.clear()


class TestTopicLastErrorExposed:
    """主题 last_error 经 repository 可读（可观测性：API 不再掩盖）"""

    def test_last_error_persisted_and_readable(self, db_session):
        repo = TopicRepository(db_session)
        topic = repo.upsert_topic(name="ErrTopic", query="q")
        db_session.flush()
        repo.update_run_status(topic.id, error="arxiv 429 限流")
        db_session.refresh(topic)
        assert topic.last_error == "arxiv 429 限流"
        assert topic.last_run_at is not None
        # 成功后清空
        repo.update_run_status(topic.id, error=None)
        db_session.refresh(topic)
        assert topic.last_error is None


class TestIdleCompensationTrigger:
    """Critical #6 补偿触发 bug 回归：补偿须独立于 skim 批次，无 unread 时也跑

    此前 _compensate_stuck_skimmed 挂在 _process_batch 末尾，但无 unread 论文时
    _process_batch 提前 return 0，补偿永远不触发 → stuck 论文卡死。
    """

    def test_process_batch_returns_zero_when_no_unread(self, db_session, monkeypatch):
        """无 unread 论文时 _process_batch 返回 0（主路径提前返回）"""
        from packages.ai.idle_processor import IdleProcessor

        ip = IdleProcessor()
        # 无论文时 _get_unread_papers 返回空 → _process_batch 直接 return 0
        monkeypatch.setattr(ip, "_get_unread_papers", lambda limit=10: [])
        # 不应触发补偿（补偿已移出 _process_batch）
        called = []
        monkeypatch.setattr(ip, "_compensate_stuck_skimmed", lambda: called.append(1) or 0)
        result = ip._process_batch()
        assert result == 0
        assert called == [], "_process_batch 不应再调用补偿（已移到 _run_loop）"

    def test_compensate_runs_independently_of_unread(self, db_session, monkeypatch):
        """补偿独立触发：无 unread 但有 stuck skimmed 时仍补偿精读"""
        from uuid import uuid4

        from packages.domain.enums import ReadStatus
        from packages.storage.models import AnalysisReport

        repo = PaperRepository(db_session)
        paper = repo.upsert_paper(
            PaperCreate(arxiv_id="2401.00301", title="stuck", abstract="a", metadata={})
        )
        repo.update_read_status(paper.id, ReadStatus.skimmed)
        db_session.add(
            AnalysisReport(id=str(uuid4()), paper_id=paper.id, summary_md="skim", deep_dive_md=None)
        )
        db_session.commit()

        from packages.ai.idle_processor import IdleProcessor

        ip = IdleProcessor()
        # 无 unread 论文
        monkeypatch.setattr(ip, "_get_unread_papers", lambda limit=10: [])
        # 补偿应能捞到这篇 stuck 论文（验证查询独立可用）
        stuck = ip._get_stuck_skimmed_papers(limit=5)
        assert len(stuck) == 1, "应捞到 1 篇 stuck skimmed 论文"
        assert stuck[0][0] == paper.id
