/**
 * LLM 配置管理 API 服务
 */

export interface LLMConfigItem {
  id: string;
  name: string;
  provider: string;
  api_base_url: string | null;
  model_skim: string;
  model_deep: string;
  model_vision: string | null;
  model_embedding: string;
  model_fallback: string;
  is_active: boolean;
}

export interface LLMConfigCreate {
  name: string;
  provider: string;
  api_key: string;
  api_base_url?: string | null;
  model_skim: string;
  model_deep: string;
  model_vision?: string | null;
  model_embedding: string;
  model_fallback: string;
}

export interface LLMConfigUpdate {
  name?: string;
  provider?: string;
  api_key?: string;
  api_base_url?: string | null;
  model_skim?: string;
  model_deep?: string;
  model_vision?: string | null;
  model_embedding?: string;
  model_fallback?: string;
}

export interface LLMConfigList {
  configs: LLMConfigItem[];
  active_id: string | null;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem("auth_token");
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  const url = `${import.meta.env.VITE_API_BASE || "http://localhost:8000"}${path}`;
  const resp = await fetch(url, {
    ...options,
    headers: {
      ...headers,
      ...(options.headers as HeadersInit),
    },
  });

  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(error.detail || "请求失败");
  }

  return resp.json();
}

export const llmConfigApi = {
  /** 获取所有配置 */
  async list(): Promise<LLMConfigList> {
    return request("/llm-configs");
  },

  /** 获取单个配置 */
  async get(configId: string): Promise<{ config: LLMConfigItem }> {
    return request(`/llm-configs/${configId}`);
  },

  /** 创建配置 */
  async create(data: LLMConfigCreate): Promise<{ config: LLMConfigItem }> {
    return request("/llm-configs", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  /** 更新配置 */
  async update(
    configId: string,
    data: LLMConfigUpdate
  ): Promise<{ config: LLMConfigItem }> {
    return request(`/llm-configs/${configId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  /** 删除配置 */
  async delete(configId: string): Promise<{ message: string }> {
    return request(`/llm-configs/${configId}`, {
      method: "DELETE",
    });
  },

  /** 激活配置 */
  async activate(configId: string): Promise<{ config: LLMConfigItem }> {
    return request("/llm-configs/activate", {
      method: "POST",
      body: JSON.stringify({ config_id: configId }),
    });
  },
};
