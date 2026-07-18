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
