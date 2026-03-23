from dataclasses import dataclass, field
from typing import Any

from packages.domain.schemas import PaperCreate


@dataclass
class AggregatedPaper:
    paper: PaperCreate
    sources: list[dict[str, Any]] = field(default_factory=list)


class ResultAggregator:
    def __init__(self):
        self.results: list[AggregatedPaper] = []

    def add_results(
        self, channel: str, papers: list[PaperCreate], metadata: dict[str, Any]
    ) -> None:
        for paper in papers:
            existing = self._find_existing(paper)
            if existing:
                existing.sources.append({"channel": channel, **metadata})
            else:
                self.results.append(
                    AggregatedPaper(
                        paper=paper,
                        sources=[{"channel": channel, **metadata}],
                    )
                )

    def _find_existing(self, paper: PaperCreate) -> AggregatedPaper | None:
        for result in self.results:
            if result.paper.doi and paper.doi and result.paper.doi == paper.doi:
                return result
        return None

    def get_sorted_results(self) -> list[AggregatedPaper]:
        return sorted(self.results, key=lambda r: len(r.sources), reverse=True)

    def get_stats(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for result in self.results:
            for source in result.sources:
                ch = source.get("channel", "unknown")
                if ch not in stats:
                    stats[ch] = {"total": 0, "new": 0, "duplicates": 0}
                stats[ch]["total"] += 1
        return stats
