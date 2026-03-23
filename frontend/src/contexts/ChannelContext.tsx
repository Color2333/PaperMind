/**
 * 渠道上下文 - 多源聚合全局状态管理
 * 管理所有渠道的默认配置、状态和用户偏好
 *
 * @author Color2333
 */

import { createContext, useContext, useState, useCallback, ReactNode, useEffect } from 'react';

export interface Channel {
  id: string;
  name: string;
  description: string;
  isFree: boolean;
  cost?: string;
  category: 'general' | 'cs' | 'biomed' | 'preprint';
  status: 'available' | 'error' | 'rate_limited' | 'disabled';
  quota?: { used: number; limit: number };
}

interface ChannelContextValue {
  channels: Channel[];
  defaultChannels: string[];
  loading: boolean;
  error: string | null;
  getChannel: (id: string) => Channel | undefined;
  updateChannelStatus: (id: string, status: Channel['status']) => void;
  setDefaultChannels: (channels: string[]) => void;
  refreshChannels: () => Promise<void>;
}

const ChannelContext = createContext<ChannelContextValue | null>(null);

export function ChannelProvider({ children }: { children: ReactNode }) {
  const [channels, setChannels] = useState<Channel[]>(INITIAL_CHANNELS);
  const [defaultChannels, setDefaultChannels] = useState<string[]>(['arxiv']);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchChannels = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/papers/suggest-channels');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      setChannels(data.channels || INITIAL_CHANNELS);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
      // 降级：使用默认渠道列表
      setChannels(INITIAL_CHANNELS);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchChannels();
  }, [fetchChannels]);

  const getChannel = useCallback(
    (id: string) => channels.find((c) => c.id === id),
    [channels],
  );

  const updateChannelStatus = useCallback(
    (id: string, status: Channel['status']) => {
      setChannels((prev) =>
        prev.map((c) => (c.id === id ? { ...c, status } : c)),
      );
    },
    [],
  );

  const setDefault = useCallback((ids: string[]) => {
    setDefaultChannels(ids);
  }, []);

  return (
    <ChannelContext.Provider
      value={{
        channels,
        defaultChannels,
        loading,
        error,
        getChannel,
        updateChannelStatus,
        setDefaultChannels: setDefault,
        refreshChannels: fetchChannels,
      }}
    >
      {children}
    </ChannelContext.Provider>
  );
}

export const useChannels = () => {
  const ctx = useContext(ChannelContext);
  if (!ctx)
    throw new Error('useChannels must be used within ChannelProvider');
  return ctx;
};

const INITIAL_CHANNELS: Channel[] = [
  {
    id: 'arxiv',
    name: 'ArXiv',
    description:
      '免费开放获取，涵盖物理学、计算机科学、数学等领域，预印本为主',
    isFree: true,
    category: 'general',
    status: 'available',
  },
  {
    id: 'openalex',
    name: 'OpenAlex',
    description:
      '全学科覆盖（2.5亿+论文），Google Scholar 替代，开源免费',
    isFree: true,
    category: 'general',
    status: 'available',
  },
  {
    id: 'semantic_scholar',
    name: 'Semantic Scholar',
    description:
      'AI 驱动的学术搜索，提供影响力引用分析和 TL;DR 摘要',
    isFree: true,
    cost: '免费 100次/5分钟，需 API Key 提升限额',
    category: 'cs',
    status: 'available',
  },
  {
    id: 'dblp',
    name: 'DBLP',
    description:
      '计算机科学会议论文权威索引（NeurIPS, ICML, CVPR, ACL 等）',
    isFree: true,
    category: 'cs',
    status: 'available',
  },
  {
    id: 'ieee',
    name: 'IEEE Xplore',
    description:
      '电气电子、计算机科学领域权威，正式出版物为主',
    isFree: false,
    cost: '$129/月 或 50 次/天免费，需 API Key',
    category: 'cs',
    status: 'available',
  },
  {
    id: 'biorxiv',
    name: 'bioRxiv',
    description: '生物学/生命科学预印本，追踪最新研究',
    isFree: true,
    category: 'preprint',
    status: 'available',
  },
];
