/**
 * IEEE 配额配置组件 - 完整版新增
 * 支持配置每日 IEEE API 调用限额
 * 
 * @author Color2333
 */

import React, { useState, useEffect } from 'react';

interface IeeeQuotaConfigProps {
  dailyQuota?: number;
  apiKeyOverride?: string;
  onChange?: (config: { dailyQuota: number; apiKeyOverride?: string }) => void;
  readOnly?: boolean;
}

export const IeeeQuotaConfig: React.FC<IeeeQuotaConfigProps> = ({
  dailyQuota = 10,
  apiKeyOverride = '',
  onChange,
  readOnly = false,
}) => {
  const [quota, setQuota] = useState(dailyQuota);
  const [apiKey, setApiKey] = useState(apiKeyOverride);
  const [showApiKey, setShowApiKey] = useState(false);

  useEffect(() => {
    setQuota(dailyQuota);
    setApiKey(apiKeyOverride);
  }, [dailyQuota, apiKeyOverride]);

  const handleQuotaChange = (value: number) => {
    const newQuota = Math.max(1, Math.min(50, value));
    setQuota(newQuota);
    onChange?.({ dailyQuota: newQuota, apiKeyOverride: apiKey || undefined });
  };

  const handleApiKeyChange = (value: string) => {
    setApiKey(value);
    onChange?.({ dailyQuota: quota, apiKeyOverride: value || undefined });
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100">
          IEEE 高级配置
        </h3>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          配置 IEEE API 配额和可选的 API Key 覆盖
        </p>
      </div>

      {/* 每日配额 */}
      <div>
        <label
          htmlFor="daily-quota"
          className="block text-sm font-medium text-gray-700 dark:text-gray-300"
        >
          每日 API 调用限额
        </label>
        <div className="mt-2 flex items-center space-x-4">
          <input
            type="number"
            id="daily-quota"
            min="1"
            max="50"
            value={quota}
            onChange={(e) => handleQuotaChange(parseInt(e.target.value) || 0)}
            disabled={readOnly}
            className="block w-32 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-800 dark:border-gray-700 dark:text-gray-100 sm:text-sm disabled:opacity-50"
          />
          <span className="text-sm text-gray-500 dark:text-gray-400">
            次/天
          </span>
          <span className="text-xs text-gray-400 dark:text-gray-500">
            (免费 API 上限：50 次/天)
          </span>
        </div>
        <div className="mt-2">
          <input
            type="range"
            min="1"
            max="50"
            value={quota}
            onChange={(e) => handleQuotaChange(parseInt(e.target.value))}
            disabled={readOnly}
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 disabled:opacity-50"
          />
        </div>
      </div>

      {/* API Key 覆盖 */}
      <div>
        <label
          htmlFor="api-key"
          className="block text-sm font-medium text-gray-700 dark:text-gray-300"
        >
          IEEE API Key（可选）
        </label>
        <div className="mt-2 relative">
          <input
            type={showApiKey ? 'text' : 'password'}
            id="api-key"
            value={apiKey}
            onChange={(e) => handleApiKeyChange(e.target.value)}
            disabled={readOnly}
            placeholder="留空则使用全局配置"
            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 dark:bg-gray-800 dark:border-gray-700 dark:text-gray-100 sm:text-sm disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => setShowApiKey(!showApiKey)}
            className="absolute inset-y-0 right-0 pr-3 flex items-center text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          >
            {showApiKey ? '🙈' : '👁️'}
          </button>
        </div>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          留空则使用 .env 中的全局 IEEE_API_KEY 配置
        </p>
      </div>

      {/* 配额使用说明 */}
      <div className="rounded-md bg-gray-50 dark:bg-gray-800 p-4">
        <h4 className="text-sm font-medium text-gray-900 dark:text-gray-100">
          💡 配额使用说明
        </h4>
        <ul className="mt-2 text-sm text-gray-600 dark:text-gray-300 space-y-1">
          <li>• 每次 IEEE 搜索会计入 1 次配额</li>
          <li>• 配额按天计算，UTC 时间 00:00 重置</li>
          <li>• 配额用尽后自动跳过 IEEE 渠道</li>
          <li>• 建议设置 10-20 次/天用于测试</li>
        </ul>
      </div>

      {/* 警告提示 */}
      {quota > 20 && (
        <div className="rounded-md bg-yellow-50 dark:bg-yellow-900/20 p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg
                className="h-5 w-5 text-yellow-400"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <div className="ml-3">
              <p className="text-sm text-yellow-800 dark:text-yellow-200">
                注意：设置较高的配额（{quota} 次/天）可能会快速消耗 IEEE 免费 API 限额。
                建议根据实际需求调整。
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default IeeeQuotaConfig;
