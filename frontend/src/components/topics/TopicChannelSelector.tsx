import React, { useState } from 'react';
import { useChannels } from '@/contexts/ChannelContext';
import { ChevronDown, Check, Globe, Cpu, BookOpen, DollarSign, FlaskConical } from 'lucide-react';

interface TopicChannelSelectorProps {
  selectedChannels?: string[];
  onChange?: (channels: string[]) => void;
  readOnly?: boolean;
}

const CATEGORY_CONFIG = [
  { id: 'general', name: '通用搜索', icon: Globe },
  { id: 'cs', name: 'AI / CS 增强', icon: Cpu },
  { id: 'preprint', name: '预印本', icon: FlaskConical },
  { id: 'paid', name: '付费渠道', icon: DollarSign },
];

export const TopicChannelSelector: React.FC<TopicChannelSelectorProps> = ({
  selectedChannels = ['arxiv'],
  onChange,
  readOnly = false,
}) => {
  const { channels } = useChannels();
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const toggleGroup = (groupId: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  };

  const handleToggle = (channelId: string) => {
    if (readOnly) return;

    const newChannels = selectedChannels.includes(channelId)
      ? selectedChannels.filter((c) => c !== channelId)
      : [...selectedChannels, channelId];

    if (newChannels.length === 0) {
      return;
    }

    onChange?.(newChannels);
  };

  const getChannelsByCategory = (category: string) => {
    return channels.filter((ch) => {
      if (category === 'cs') return ch.category === 'cs' && ch.id !== 'ieee';
      if (category === 'paid') return ch.id === 'ieee';
      return ch.category === category;
    });
  };

  const getSelectedCount = (category: string) => {
    return getChannelsByCategory(category).filter((ch) =>
      selectedChannels.includes(ch.id),
    ).length;
  };

  const isGroupAllSelected = (category: string) => {
    const groupChannels = getChannelsByCategory(category);
    return groupChannels.every((ch) => selectedChannels.includes(ch.id));
  };

  const toggleGroupAll = (category: string) => {
    const groupChannels = getChannelsByCategory(category);
    const allSelected = isGroupAllSelected(category);

    let newChannels: string[];
    if (allSelected) {
      newChannels = selectedChannels.filter(
        (id) => !groupChannels.some((ch) => ch.id === id),
      );
      if (newChannels.length === 0) return;
    } else {
      const groupIds = groupChannels.map((ch) => ch.id);
      const otherChannels = selectedChannels.filter(
        (id) => !groupIds.includes(id),
      );
      newChannels = [...otherChannels, ...groupIds];
    }

    onChange?.(newChannels);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-medium text-gray-900 dark:text-gray-100">
          论文渠道
        </h3>
        {readOnly && (
          <span className="text-sm text-gray-500">只读</span>
        )}
      </div>

      {CATEGORY_CONFIG.map(({ id, name, icon: Icon }) => {
        const isCollapsed = collapsedGroups.has(id);
        const groupChannels = getChannelsByCategory(id);
        const selectedCount = getSelectedCount(id);

        if (groupChannels.length === 0) return null;

        return (
          <div
            key={id}
            className="border rounded-lg overflow-hidden dark:border-gray-700"
          >
            <button
              type="button"
              onClick={() => toggleGroup(id)}
              className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-gray-500" />
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {name}
                </span>
                <span className="text-xs text-gray-500">
                  ({selectedCount}/{groupChannels.length})
                </span>
              </div>
              <ChevronDown
                className={`h-4 w-4 text-gray-400 transition-transform ${
                  isCollapsed ? '-rotate-90' : ''
                }`}
              />
            </button>

            {!isCollapsed && (
              <div className="p-3 space-y-2">
                {groupChannels.map((channel) => {
                  const isSelected = selectedChannels.includes(channel.id);
                  return (
                    <button
                      type="button"
                      key={channel.id}
                      onClick={() => handleToggle(channel.id)}
                      disabled={readOnly}
                      className={`
                        w-full text-left relative flex items-start gap-3 p-3 rounded-lg border
                        transition-all duration-150
                        ${readOnly ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer hover:border-gray-400'}
                        ${
                          isSelected
                            ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
                            : 'border-gray-200 bg-white dark:bg-gray-900 dark:border-gray-700'
                        }
                      `}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm text-gray-900 dark:text-gray-100">
                            {channel.name}
                          </span>
                          {channel.isFree ? (
                            <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">
                              免费
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-800 dark:bg-orange-900/30 dark:text-orange-400">
                              付费
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
                          {channel.description}
                        </p>
                        {channel.cost && (
                          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                            {channel.cost}
                          </p>
                        )}
                      </div>

                      <div
                        className={`
                          flex-shrink-0 flex items-center justify-center w-5 h-5 rounded border
                          ${
                            isSelected
                              ? 'bg-blue-500 border-blue-500 text-white'
                              : 'border-gray-300 bg-white dark:bg-gray-800 dark:border-gray-600'
                          }
                        `}
                      >
                        {isSelected && <Check className="h-3 w-3" />}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {selectedChannels.includes('ieee') && (
        <div className="rounded-lg bg-blue-50 dark:bg-blue-900/20 p-4 mt-4">
          <div className="flex gap-3">
            <BookOpen className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium text-blue-800 dark:text-blue-200">
                IEEE 配置提示
              </p>
              <ul className="mt-2 space-y-1 text-blue-700 dark:text-blue-300">
                <li>• 需在 .env 中设置 IEEE_API_KEY</li>
                <li>• 免费版限制：50 次/天</li>
                <li>• 建议在主题设置中配置独立配额</li>
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TopicChannelSelector;
