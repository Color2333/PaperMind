import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from packages.domain.schemas import PaperCreate
from packages.integrations.aggregator import ResultAggregator
from packages.integrations.registry import ChannelRegistry

logger = logging.getLogger(__name__)


@dataclass
class ChannelResult:
    channel: str
    papers: list[PaperCreate]
    metadata: dict[str, Any]
    error: str | None = None


class ChannelWorkerPool:
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_all(
        self,
        query: str,
        channels: list[str],
        max_per_channel: int = 50,
    ) -> list[ChannelResult]:
        ChannelRegistry.register_default_channels()

        tasks = [self._fetch_channel(ch, query, max_per_channel) for ch in channels]
        return await asyncio.gather(*tasks)

    async def _fetch_channel(self, channel: str, query: str, max_results: int) -> ChannelResult:
        async with self.semaphore:
            try:
                ch = ChannelRegistry.get(channel)
                if not ch:
                    return ChannelResult(channel, [], {}, error="channel not found")

                papers = await asyncio.to_thread(ch.fetch, query, max_results)
                return ChannelResult(
                    channel=channel,
                    papers=papers,
                    metadata={"total": len(papers)},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Channel %s failed: %s", channel, exc)
                return ChannelResult(channel, [], {}, error=str(exc))

    async def fetch_and_aggregate(
        self,
        query: str,
        channels: list[str],
        max_per_channel: int = 50,
    ) -> tuple[ResultAggregator, list[ChannelResult]]:
        results = await self.fetch_all(query, channels, max_per_channel)

        aggregator = ResultAggregator()
        for result in results:
            if result.error:
                logger.warning("Channel %s failed: %s", result.channel, result.error)
                continue
            aggregator.add_results(result.channel, result.papers, result.metadata)

        return aggregator, results
