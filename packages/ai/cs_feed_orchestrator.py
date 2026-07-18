"""CS 分类订阅调度器
@author Color2333
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from html import escape as html_escape

from packages.integrations.arxiv_client import ArxivClient
from packages.storage.db import SessionLocal
from packages.storage.repositories import CSFeedRepository

logger = logging.getLogger(__name__)

TOKEN_BUCKET_SIZE = 20
TOKEN_FILL_RATE = 20
REQUEST_INTERVAL = 3
COOL_DOWN_MINUTES = 30


class TokenBucket:
    def __init__(self, size: int, fill_rate: int):
        self.size = size
        self.tokens = float(size)
        self.fill_rate = fill_rate
        self.last_refill = time.time()
        self.lock = threading.Lock()

    def acquire(self, timeout: float = 60) -> bool:
        # 修超时判定 bug：此前用 last_refill（每次 _refill 都更新为 now），time.time()-last_refill
        # 永远≈0，永不超时 → arxiv 全局限流时 acquire 卡死 worker 线程。改用 start_time 判定
        start_time = time.time()
        while True:
            with self.lock:
                self._refill()
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
            if time.time() - start_time > timeout:
                return False
            time.sleep(1)

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        new_tokens = elapsed * (self.fill_rate / 60)
        self.tokens = min(self.size, self.tokens + new_tokens)
        self.last_refill = now


class CSFeedOrchestrator:
    def __init__(self):
        self.bucket = TokenBucket(TOKEN_BUCKET_SIZE, TOKEN_FILL_RATE)

    def sync_categories(self):
        """从 arXiv 拉取分类并写入 DB"""
        client = ArxivClient()
        cats = client.fetch_categories()
        session = SessionLocal()
        try:
            repo = CSFeedRepository(session)
            for c in cats:
                repo.upsert_category(c["code"], c["name"], c.get("description", ""))
            logger.info("[CSFeed] Synced %d categories", len(cats))
        finally:
            session.close()

    def run(self):
        """每小时执行一次（High 3a：每 sub 独立 session，异常隔离）"""
        # 先读订阅列表（独立 session，读后即关）
        read_session = SessionLocal()
        try:
            repo = CSFeedRepository(read_session)
            subs = repo.get_active_subscriptions()
            sub_specs = [
                (
                    s.category_code,
                    s.status,
                    s.cool_down_until,
                    s.last_run_at,
                    s.last_run_count,
                    s.daily_limit,
                )
                for s in subs
            ]
        finally:
            read_session.close()

        now = datetime.now(UTC)
        digest: list[tuple[str, int, list[str]]] = []

        for (
            category_code,
            status,
            cool_down_until,
            last_run_at,
            last_run_count,
            daily_limit,
        ) in sub_specs:
            # 冷却中检查
            if status == "cool_down" and cool_down_until and now < cool_down_until:
                logger.info(
                    "[CSFeed] Skipping %s (cool down until %s)",
                    category_code,
                    cool_down_until,
                )
                continue

            # 每日配额检查
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if last_run_at and last_run_at >= today_start:
                remaining = daily_limit - last_run_count
            else:
                remaining = daily_limit

            if remaining <= 0:
                logger.info("[CSFeed] Skipping %s (daily limit reached)", category_code)
                continue

            # 请求间隔
            if not self.bucket.acquire(timeout=30):
                logger.warning("[CSFeed] Token bucket timeout, skipping %s", category_code)
                continue
            time.sleep(REQUEST_INTERVAL)

            # 每 sub 独立 session：一个 sub 抓取异常不会污染下个 sub 的脏数据
            sub_session = SessionLocal()
            try:
                sub_repo = CSFeedRepository(sub_session)
                client = ArxivClient()
                papers = client.fetch_latest(
                    query=f"cat:{category_code}",
                    max_results=remaining,
                    days_back=7,
                )
                from packages.storage.repositories import PaperRepository

                paper_repo = PaperRepository(sub_session)
                count = 0
                titles: list[str] = []
                paper_ids: list[str] = []
                for p in papers:
                    saved = paper_repo.upsert_paper(p)
                    count += 1
                    paper_ids.append(saved.id)
                    title = getattr(p, "title", None)
                    if title:
                        titles.append(title)

                # 关联论文到 cs_feed 分类对应的 topic（每分类一个 disabled topic）
                # 使 cs_feed 论文接入主题侧边栏/图谱/统计。enabled=False 防
                # topic_dispatch 重复抓取同一分类（仅 cs_feed_dispatch 负责）
                if paper_ids:
                    self._link_cs_papers_to_topic(sub_session, category_code, paper_ids)

                sub_repo.update_run_status(category_code, count)
                sub_session.commit()
                logger.info("[CSFeed] %s: ingested %d papers", category_code, count)
                if count > 0:
                    digest.append((category_code, count, titles))
                    # High 3b：抓取的论文触发 embed + skim（复用 PaperPipelines），
                    # 此前 cs_feed 论文处于 unread 无 embedding 无 topic，只能靠
                    # idle_processor 事后补——改为抓取即处理
                    self._process_cs_papers(paper_ids)
                    # 抓取后触发引用自动关联（与 ingest_arxiv 对齐，此前 cs_feed 缺这步）
                    self._trigger_auto_link(paper_ids)
            except Exception as e:
                sub_session.rollback()
                err_str = str(e)
                if "429" in err_str or "Too Many Requests" in err_str:
                    # 冷却设置需独立 session（当前已回滚）
                    cool_session = SessionLocal()
                    try:
                        CSFeedRepository(cool_session).set_cool_down(
                            category_code, now + timedelta(minutes=COOL_DOWN_MINUTES)
                        )
                        cool_session.commit()
                    finally:
                        cool_session.close()
                    logger.warning("[CSFeed] Rate limited %s, cool down 30min", category_code)
                else:
                    logger.error("[CSFeed] Error fetching %s: %s", category_code, e)
            finally:
                sub_session.close()

        # 入库后推送邮件摘要（README 宣传的「邮件推送」）；SMTP 未配置时静默跳过
        if digest:
            self._notify_digest(digest)

    def _process_cs_papers(self, paper_ids: list[str]) -> None:
        """对 cs_feed 抓取的论文触发 embed + skim（High 3b，抓取即处理）。

        复用 PaperPipelines 的 embed_paper / skim，使 cs_feed 论文不再只入库后
        处于 unread 无 embedding 状态。失败不抛（仅记录日志），不阻断抓取主流程。
        """
        if not paper_ids:
            return
        from packages.ai.pipelines import PaperPipelines
        from packages.ai.rate_limiter import acquire_api, get_rate_limiter

        pipelines = PaperPipelines()
        limiter = get_rate_limiter()
        for pid in paper_ids:
            if not limiter.start_task():
                logger.debug("[CSFeed] 并发满，跳过处理 %s", pid)
                break
            try:
                if not acquire_api("embedding", timeout=30.0):
                    logger.warning("[CSFeed] Embedding 限流，跳过 %s", pid)
                    continue
                try:
                    pipelines.embed_paper(pid)
                except Exception as e:
                    logger.warning("[CSFeed] embed %s 失败: %s", pid, e)
                    continue
                if not acquire_api("llm", timeout=30.0):
                    logger.warning("[CSFeed] LLM 限流，跳过 skim %s", pid)
                    continue
                try:
                    pipelines.skim(pid)
                except Exception as e:
                    logger.warning("[CSFeed] skim %s 失败: %s", pid, e)
            finally:
                limiter.end_task()

    @staticmethod
    def _link_cs_papers_to_topic(session, category_code: str, paper_ids: list[str]) -> None:
        """把 cs_feed 抓取的论文关联到对应分类的 topic（每分类一个 disabled topic）。

        命名约定：topic name = `csfeed:{category_code}`，query = `cat:{category_code}`，
        enabled=False（防 topic_dispatch 重复抓取同一分类，仅 cs_feed_dispatch 负责）。
        upsert_topic 按 name 幂等，link_to_topic 受 uq_paper_topic 约束兜底幂等。
        关联后 cs_feed 论文即接入主题侧边栏/图谱视图/统计/推荐 boost。
        """
        from packages.storage.repositories import PaperRepository, TopicRepository

        topic_repo = TopicRepository(session)
        topic = topic_repo.upsert_topic(
            name=f"csfeed:{category_code}",
            query=f"cat:{category_code}",
            enabled=False,
        )
        paper_repo = PaperRepository(session)
        for pid in paper_ids:
            paper_repo.link_to_topic(pid, topic.id)

    @staticmethod
    def _trigger_auto_link(paper_ids: list[str]) -> None:
        """抓取后触发引用自动关联（复用 paper_pipelines 的有界线程池）。

        此前 cs_feed 只入库不 auto_link，论文间引用关系靠后续 sync_incremental 补。
        与 ingest_arxiv 对齐，抓取即提交后台关联。
        """
        if not paper_ids:
            return
        try:
            from packages.ai.pipelines.paper_pipelines import _auto_link_pool, _bg_auto_link

            _auto_link_pool.submit(_bg_auto_link, paper_ids)
        except Exception as exc:
            logger.warning("[CSFeed] 触发 auto_link 失败: %s", exc)

    def _notify_digest(self, digest: list[tuple[str, int, list[str]]]) -> None:
        """抓取入库后发送邮件摘要；SMTP 未配置或无收件人时静默跳过"""
        from packages.config import get_settings
        from packages.integrations.notifier import NotificationService

        settings = get_settings()
        recipient = settings.notify_default_to
        if not recipient:
            return

        total = sum(count for _, count, _ in digest)
        rows = "".join(
            f"<tr><td>{html_escape(cat)}</td><td style='text-align:right'>{count}</td></tr>"
            for cat, count, _ in digest
        )
        title_blocks: list[str] = []
        for cat, count, titles in digest:
            if not titles:
                continue
            sample = "".join(f"<li>{html_escape(t)}</li>" for t in titles[:3])
            more = f"<li>… 共 {count} 篇</li>" if count > len(titles) else ""
            title_blocks.append(
                f"<p><b>{html_escape(cat)}</b>（{count} 篇）</p><ul>{sample}{more}</ul>"
            )
        body = (
            "<h2>CS 订阅抓取摘要</h2>"
            f"<p>本次新增 <b>{total}</b> 篇论文，涉及 {len(digest)} 个分类：</p>"
            "<table border='1' cellpadding='6' style='border-collapse:collapse'>"
            f"<tr><th>分类</th><th>新增</th></tr>{rows}</table>"
            f"{''.join(title_blocks)}"
        )
        ok = NotificationService().send_email_html(
            recipient, f"[PaperMind] CS 订阅抓取摘要 · 新增 {total} 篇", body
        )
        if ok:
            logger.info("[CSFeed] Digest email sent to %s (%d papers)", recipient, total)
        else:
            logger.debug("[CSFeed] SMTP not configured, skip digest email")
