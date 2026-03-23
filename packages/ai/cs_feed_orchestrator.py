"""CS 分类订阅调度器
@author Color2333
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

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
        while True:
            with self.lock:
                self._refill()
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
            if time.time() - self.last_refill > timeout:
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
        """每小时执行一次"""
        session = SessionLocal()
        try:
            repo = CSFeedRepository(session)
            subs = repo.get_active_subscriptions()
            now = datetime.now(UTC)

            for sub in subs:
                # 冷却中检查
                if sub.status == "cool_down" and sub.cool_down_until:
                    if now < sub.cool_down_until:
                        logger.info(
                            "[CSFeed] Skipping %s (cool down until %s)",
                            sub.category_code,
                            sub.cool_down_until,
                        )
                        continue

                # 每日配额检查
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                if sub.last_run_at and sub.last_run_at >= today_start:
                    remaining = sub.daily_limit - sub.last_run_count
                else:
                    remaining = sub.daily_limit

                if remaining <= 0:
                    logger.info("[CSFeed] Skipping %s (daily limit reached)", sub.category_code)
                    continue

                # 请求间隔
                if not self.bucket.acquire(timeout=30):
                    logger.warning("[CSFeed] Token bucket timeout, skipping %s", sub.category_code)
                    continue
                time.sleep(REQUEST_INTERVAL)

                # 抓取
                try:
                    client = ArxivClient()
                    papers = client.fetch_latest(
                        query=f"cat:{sub.category_code}",
                        max_results=remaining,
                        days_back=7,
                    )
                    from packages.storage.repositories import PaperRepository

                    paper_repo = PaperRepository(session)
                    count = 0
                    for p in papers:
                        paper_repo.upsert_paper(p)
                        count += 1

                    repo.update_run_status(sub.category_code, count)
                    logger.info("[CSFeed] %s: ingested %d papers", sub.category_code, count)

                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "Too Many Requests" in err_str:
                        repo.set_cool_down(
                            sub.category_code, now + timedelta(minutes=COOL_DOWN_MINUTES)
                        )
                        logger.warning(
                            "[CSFeed] Rate limited %s, cool down 30min", sub.category_code
                        )
                    else:
                        logger.error("[CSFeed] Error fetching %s: %s", sub.category_code, e)
        finally:
            session.close()
