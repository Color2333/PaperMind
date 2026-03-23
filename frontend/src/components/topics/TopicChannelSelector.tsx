/**
 * 主题渠道选择组件 - 多源聚合版
 * 支持 ArXiv、IEEE、OpenAlex、Semantic Scholar、DBLP、bioRxiv 多渠道选择
 *
 * @author Color2333
 */

import React, { useState, useEffect } from 'react';

interface ChannelOption {
  id: string;
  name: string;
  description: string;
  isFree: boolean;
  cost?: string;
  category?: 'general' | 'cs' | 'biomed' | 'preprint';
}

interface TopicChannelSelectorProps {
  selectedChannels?: string[];
  onChange?: (channels: string[]) => void;
  readOnly?: boolean;
}

const CHANNEL_OPTIONS: ChannelOption[] = [
  // === 通用搜索渠道 ===
  {
    id: 'arxiv',
    name: 'ArXiv',
    description: '免费开放获取，涵盖物理学、计算机科学、数学等领域，预印本为主',
    isFree: true,
    category: 'general',
  },
  {
    id: 'openalex',
    name: 'OpenAlex',
    description: '全学科覆盖（2.5亿+论文），Google Scholar 替代，开源免费',
    isFree: true,
    category: 'general',
  },
  // === AI/ML 增强渠道 ===
  {
    id: 'semantic_scholar',
    name: 'Semantic Scholar',
    description: 'AI 驱动的学术搜索，提供影响力引用分析和 TL;DR 摘要',
    isFree: true,  // 有免费额度
    cost: '免费 100次/5分钟，需 API Key 提升限额',
    category: 'cs',
  },
  // === CS 会议专用 ===
  {
    id: 'dblp',
    name: 'DBLP',
    description: '计算机科学会议论文权威索引（NeurIPS, ICML, CVPR, ACL 等）',
    isFree: true,
    category: 'cs',
  },
  // === IEEE 付费渠道 ===
  {
    id: 'ieee',
    name: 'IEEE Xplore',
    description: '电气电子、计算机科学领域权威，正式出版物为主',
    isFree: false,
    cost: '$129/月 或 50 次/天免费，需 API Key',
    category: 'cs',
  },
  // === 预印本渠道 ===
  {
    id: 'biorxiv',
    name: 'bioRxiv',
    description: '生物学/生命科学预印本，追踪最新研究',
    isFree: true,
    category: 'preprint',
  },
];

export const TopicChannelSelector: React.FC<TopicChannelSelectorProps> = ({
  selectedChannels = ['arxiv'],
  onChange,
  readOnly = false,
}) => {
  const [channels, setChannels] = useState<string[]>(selectedChannels);

  useEffect(() => {
    setChannels(selectedChannels);
  }, [selectedChannels]);

  const handleToggle = (channelId: string) => {
    if (readOnly) return;

    const newChannels = channels.includes(channelId)
      ? channels.filter((c) => c !== channelId)
      : [...channels, channelId];

    // 至少保留一个渠道
    if (newChannels.length === 0) {
      alert('请至少选择一个渠道');
      return;
    }

    setChannels(newChannels);
    onChange?.(newChannels);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100">
          论文渠道
        </h3>
        {readOnly && (
          <span className="text-sm text-gray-500">只读模式</span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {CHANNEL_OPTIONS.map((option) => {
          const isSelected = channels.includes(option.id);
          return (
            <div
              key={option.id}
              onClick={() => handleToggle(option.id)}
              className={`
                relative flex cursor-pointer rounded-lg border p-4 shadow-sm
                transition-all duration-200
                ${
                  readOnly
                    ? 'cursor-not-allowed opacity-75'
                    : 'hover:shadow-md'
                }
                ${
                  isSelected
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-300 bg-white dark:bg-gray-800 dark:border-gray-700'
                }
              `}
            >
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {option.name}
                  </h4>
                  {option.isFree ? (
                    <span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">
                      免费
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-orange-100 px-2.5 py-0.5 text-xs font-medium text-orange-800 dark:bg-orange-900/30 dark:text-orange-400">
                      付费
                    </span>
                  )}
                </div>
                <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                  {option.description}
                </p>
                {option.cost && (
                  <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                    💰 {option.cost}
                  </p>
                )}
                <div className="mt-3 flex items-center">
                  <input
                    type="checkbox"
                    checked={isSelected}
                    readOnly
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="ml-2 text-sm text-gray-600 dark:text-gray-300">
                    {isSelected ? '已启用' : '未启用'}
                  </span>
                </div>
              </div>

              {isSelected && (
                <div className="absolute top-2 right-2">
                  <svg
                    className="h-5 w-5 text-blue-500"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                      clipRule="evenodd"
                    />
                  </svg>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {channels.includes('ieee') && (
        <div className="mt-4 rounded-md bg-blue-50 dark:bg-blue-900/20 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg
                className="h-5 w-5 text-blue-400"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <div className="ml-3">
              <h4 className="text-sm font-medium text-blue-800 dark:text-blue-200">
                IEEE 配置提示
              </h4>
              <div className="mt-2 text-sm text-blue-700 dark:text-blue-300">
                <ul className="list-disc list-inside space-y-1">
                  <li>需要在 .env 中设置 IEEE_API_KEY</li>
                  <li>免费版限制：50 次 API 调用/天</li>
                  <li>IEEE PDF 暂不支持在线阅读</li>
                  <li>建议在主题设置中配置独立配额</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TopicChannelSelector;
