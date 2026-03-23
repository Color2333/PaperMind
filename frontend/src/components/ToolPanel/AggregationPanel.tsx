import { useState, useCallback } from 'react';
import { Sparkles, Search as SearchIcon, Loader2 } from 'lucide-react';
import { MultiSourceSearchBar } from '@/components/search/MultiSourceSearchBar';

interface SearchResult {
  id: string;
  title: string;
  authors?: string[];
  abstract?: string;
  source: string;
  url?: string;
  publishedDate?: string;
}

interface AggregationPanelProps {
  selectedText: string;
  paperId: string;
}

export function AggregationPanel({ selectedText, paperId }: AggregationPanelProps) {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);

  const handleSearch = useCallback(async (query: string, channels: string[]) => {
    setLoading(true);
    try {
      const token = localStorage.getItem('auth_token') || '';
      const base = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
      const res = await fetch(`${base}/papers/multi-source-search?query=${encodeURIComponent(query)}&channels=${channels.join(',')}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (res.ok) {
        const data = await res.json();
        setResults(data.results || []);
      }
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-white/10 px-4 py-3">
        <div className="mb-2 flex items-center gap-2 text-sm text-white/60">
          <Sparkles className="h-4 w-4 text-primary" />
          <span>AI 聚合搜索</span>
        </div>
        <MultiSourceSearchBar onSearch={handleSearch} loading={loading} />
      </div>

      <div className="flex-1 overflow-auto px-4 py-3">
        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        )}

        {!loading && results.length === 0 && (
          <div className="flex flex-col items-center gap-3 pt-8 text-center">
            <SearchIcon className="h-10 w-10 text-white/10" />
            <p className="text-sm text-white/40">输入关键词搜索</p>
            <p className="text-xs text-white/20">AI 将从多源聚合相关论文</p>
          </div>
        )}

        {results.map((result, idx) => (
          <div key={result.id || idx} className="mb-3 rounded-lg border border-white/10 p-3">
            <h4 className="mb-1 text-sm font-medium text-white/90 line-clamp-2">{result.title}</h4>
            {result.authors && result.authors.length > 0 && (
              <p className="mb-1 text-xs text-white/40">{result.authors.slice(0, 3).join(', ')}</p>
            )}
            {result.source && (
              <span className="inline-block rounded bg-primary/20 px-2 py-0.5 text-[10px] text-primary">
                {result.source}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
