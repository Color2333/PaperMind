import { useState } from 'react';
import { ChevronDown, ExternalLink, Star, AlertCircle } from 'lucide-react';

export interface SearchPaperSource {
  channel: string;
  externalId: string;
  citations?: number;
  impactFactor?: number;
  tldr?: string;
  url?: string;
}

export interface SearchPaper {
  id: string;
  title: string;
  authors: string[];
  year?: number;
  venue?: string;
  abstract?: string;
  citations?: number;
  sources: SearchPaperSource[];
}

export interface ChannelStat {
  total: number;
  new: number;
  duplicates: number;
  error?: string;
}

interface SearchResultsListProps {
  results: SearchPaper[];
  channelStats: Record<string, ChannelStat>;
  loading?: boolean;
  onPaperClick?: (paper: SearchPaper) => void;
  filterChannel: string | null;
  onFilterChange: (channel: string | null) => void;
}

export function SearchResultsList({
  results,
  channelStats,
  loading,
  onPaperClick,
  filterChannel,
  onFilterChange,
}: SearchResultsListProps) {
  const [expandedPaper, setExpandedPaper] = useState<string | null>(null);

  const filtered = filterChannel
    ? results.filter((p) => p.sources.some((s) => s.channel === filterChannel))
    : results;

  const totalResults = Object.values(channelStats).reduce(
    (sum, s) => sum + s.total,
    0,
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-gray-500">搜索中...</div>
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-500">
        <AlertCircle className="h-12 w-12 mb-4" />
        <p>暂无结果，请尝试其他关键词或渠道</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 text-sm">
          <span className="text-gray-600 dark:text-gray-400">
            共 {totalResults} 篇，来自
          </span>
          {Object.entries(channelStats).map(([ch, stat]) => (
            <div
              key={ch}
              className={`px-2 py-0.5 rounded text-xs ${
                stat.error
                  ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                  : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'
              }`}
            >
              {ch}: {stat.total}
              {stat.error && ` (${stat.error})`}
            </div>
          ))}
        </div>

        <select
          value={filterChannel || ''}
          onChange={(e) => onFilterChange(e.target.value || null)}
          className="border rounded px-2 py-1 text-sm bg-white dark:bg-gray-800 dark:border-gray-700"
        >
          <option value="">全部渠道</option>
          {Object.keys(channelStats).map((ch) => (
            <option key={ch} value={ch}>
              {ch}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-3">
        {filtered.map((paper) => {
          const isExpanded = expandedPaper === paper.id;
          const primarySource = paper.sources[0];

          return (
            <div
              key={paper.id}
              className="border rounded-lg bg-white dark:bg-gray-900 dark:border-gray-700 overflow-hidden"
            >
              <button
                type="button"
                className="w-full text-left p-4 cursor-pointer"
                onClick={() => {
                  setExpandedPaper(isExpanded ? null : paper.id);
                  onPaperClick?.(paper);
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-gray-900 dark:text-gray-100 line-clamp-2">
                      {paper.title}
                    </h3>
                    <div className="mt-1 flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 flex-wrap">
                      {paper.authors.slice(0, 3).join(', ')}
                      {paper.authors.length > 3 && ' et al.'}
                      {paper.year && <span>· {paper.year}</span>}
                      {paper.venue && <span>· {paper.venue}</span>}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 flex-shrink-0">
                    {paper.citations !== undefined && (
                      <span className="inline-flex items-center gap-1 text-sm text-gray-500">
                        <Star className="h-3.5 w-3.5" />
                        {paper.citations}
                      </span>
                    )}
                    <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                      {primarySource?.channel}
                    </span>
                    <ChevronDown
                      className={`h-4 w-4 text-gray-400 transition-transform ${
                        isExpanded ? 'rotate-180' : ''
                      }`}
                    />
                  </div>
                </div>

                {paper.abstract && (
                  <p className="mt-2 text-sm text-gray-600 dark:text-gray-400 line-clamp-2">
                    {paper.abstract}
                  </p>
                )}
              </button>

              {isExpanded && paper.sources.length > 1 && (
                <div className="px-4 pb-4 border-t dark:border-gray-700">
                  <table className="w-full mt-3 text-xs">
                    <thead>
                      <tr className="text-left text-gray-500">
                        <th className="pb-2">渠道</th>
                        <th className="pb-2">外部ID</th>
                        <th className="pb-2">引用</th>
                        <th className="pb-2">影响因子</th>
                        <th className="pb-2">特殊</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paper.sources.map((source) => (
                        <tr
                          key={source.channel}
                          className="border-t dark:border-gray-800"
                        >
                          <td className="py-2 font-medium">{source.channel}</td>
                          <td className="py-2 font-mono text-gray-500">
                            {source.externalId.slice(0, 20)}...
                          </td>
                          <td className="py-2">{source.citations ?? '-'}</td>
                          <td className="py-2">
                            {source.impactFactor ?? '-'}
                          </td>
                          <td className="py-2">
                            {source.tldr && (
                              <span className="text-green-600">TL;DR</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {isExpanded && primarySource?.url && (
                <div className="px-4 pb-4 border-t dark:border-gray-700">
                  <a
                    href={primarySource.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-sm text-blue-500 hover:text-blue-600"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    在 {primarySource.channel} 查看
                  </a>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default SearchResultsList;
