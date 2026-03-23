import React, { useState, useCallback } from 'react';
import { Search, Loader2, Sparkles } from 'lucide-react';
import { useChannels } from '@/contexts/ChannelContext';

interface MultiSourceSearchBarProps {
  onSearch: (query: string, channels: string[]) => void;
  loading?: boolean;
}

interface ChannelSuggestion {
  recommended: string[];
  alternatives: string[];
  reasoning: string;
}

export const MultiSourceSearchBar: React.FC<MultiSourceSearchBarProps> = ({
  onSearch,
  loading = false,
}) => {
  const [query, setQuery] = useState('');
  const [selectedChannels, setSelectedChannels] = useState<string[]>(['arxiv']);
  const [suggestions, setSuggestions] = useState<ChannelSuggestion | null>(null);
  const { channels } = useChannels();

  const fetchSuggestions = useCallback(async (q: string) => {
    if (!q.trim()) {
      setSuggestions(null);
      return;
    }
    fetch(`/papers/suggest-channels?query=${encodeURIComponent(q)}`, {
      headers: {
        Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
      },
    })
      .then((res) => res.ok && res.json())
      .then((data) => data && setSuggestions(data))
      .catch(() => {});
  }, []);

  const handleQueryChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    fetchSuggestions(val);
  };

  const handleChannelToggle = (channelId: string) => {
    setSelectedChannels((prev) =>
      prev.includes(channelId)
        ? prev.filter((id) => id !== channelId)
        : [...prev, channelId],
    );
  };

  const handleSearch = () => {
    if (!query.trim() || selectedChannels.length === 0) return;
    onSearch(query, selectedChannels);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  const applyRecommendation = () => {
    if (suggestions?.recommended) {
      setSelectedChannels(suggestions.recommended);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            value={query}
            onChange={handleQueryChange}
            onKeyDown={handleKeyDown}
            placeholder="输入关键词，如 machine learning transformer"
            className="w-full pl-10 pr-4 py-2.5 border rounded-lg bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>
        <button
          type="button"
          onClick={handleSearch}
          disabled={!query.trim() || selectedChannels.length === 0 || loading}
          className="px-5 py-2.5 bg-blue-500 text-white rounded-lg font-medium hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              搜索中
            </>
          ) : (
            <>
              <Search className="h-4 w-4" />
              搜索
            </>
          )}
        </button>
      </div>

      {suggestions && suggestions.recommended.length > 0 && (
        <div className="flex items-center gap-2 text-sm">
          <Sparkles className="h-4 w-4 text-purple-500" />
          <span className="text-gray-600 dark:text-gray-400">
            推荐渠道：
          </span>
          <div className="flex items-center gap-1.5 flex-wrap">
            {suggestions.recommended.map((id) => {
              const ch = channels.find((c) => c.id === id);
              return ch ? (
                <span
                  key={id}
                  className="inline-flex items-center px-2 py-0.5 rounded-full bg-purple-100 text-purple-800 text-xs dark:bg-purple-900/30 dark:text-purple-400"
                >
                  {ch.name}
                </span>
              ) : null;
            })}
          </div>
          {JSON.stringify(suggestions.recommended.sort()) !== JSON.stringify(selectedChannels.sort()) && (
            <button
              type="button"
              onClick={applyRecommendation}
              className="text-blue-500 hover:text-blue-600 text-xs"
            >
              应用推荐
            </button>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm text-gray-500 dark:text-gray-400">渠道：</span>
        {channels.map((channel) => {
          const isSelected = selectedChannels.includes(channel.id);
          return (
            <button
              key={channel.id}
              type="button"
              onClick={() => handleChannelToggle(channel.id)}
              className={`
                inline-flex items-center px-3 py-1 rounded-full text-sm border transition-all
                ${
                  isSelected
                    ? 'bg-blue-500 text-white border-blue-500'
                    : 'bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-700 hover:border-gray-400'
                }
              `}
            >
              {channel.name}
              {channel.status === 'rate_limited' && (
                <span className="ml-1 text-xs">⚠️</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default MultiSourceSearchBar;
