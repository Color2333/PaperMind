/**
 * IEEE 集成 - 类型定义
 * 
 * @author Color2333
 */

export interface TopicChannelSelectorProps {
  selectedChannels?: string[];
  onChange?: (channels: string[]) => void;
  readOnly?: boolean;
}

export interface IeeeQuotaConfigProps {
  dailyQuota?: number;
  apiKeyOverride?: string;
  onChange?: (config: { dailyQuota: number; apiKeyOverride?: string }) => void;
  readOnly?: boolean;
}

export interface TopicFormData {
  name: string;
  query: string;
  enabled: boolean;
  maxResultsPerRun: number;
  sources: string[];
  ieeeDailyQuota: number;
  ieeeApiKeyOverride?: string;
}
