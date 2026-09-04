// Package llm 实现 OpenAI-compatible LLM 客户端（SSE streaming + provider 路由）。
//
// 支持所有 OpenAI-compatible API：xiaomi / zhipu / openai / anthropic（completions 协议）。
// Provider 路由通过 LLMConfig 注册；每个 provider 有独立的 baseURL + apiKey + model。
package llm

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Message 是 chat completion 的单条消息。
type Message struct {
	Role       string     `json:"role"` // system / user / assistant / tool
	Content    any        `json:"content,omitempty"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID string     `json:"tool_call_id,omitempty"`
}

// ToolCall 是 assistant 消息中的工具调用。
type ToolCall struct {
	ID       string `json:"id"`
	Type     string `json:"type"` // "function"
	Function FuncCall
}

// FuncCall 是工具调用的函数名和参数。
type FuncCall struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"` // JSON string
}

// Tool 是 LLM 可调用的工具定义（OpenAI function calling 格式）。
type Tool struct {
	Type     string `json:"type"` // "function"
	Function ToolFunction
}

// ToolFunction 是工具的名称、描述和参数 schema。
type ToolFunction struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

// CompletionRequest 是 chat completion 请求体。
type CompletionRequest struct {
	Model       string    `json:"model"`
	Messages    []Message `json:"messages"`
	Stream      bool      `json:"stream"`
	Temperature *float64  `json:"temperature,omitempty"`
	MaxTokens   *int      `json:"max_tokens,omitempty"`
	Tools       []Tool    `json:"tools,omitempty"`
}

// CompletionResponse 是非流式响应（解析 SSE 后重组）。
type CompletionResponse struct {
	Content      string
	ToolCalls    []ToolCall
	FinishReason string
	InputTokens  int
	OutputTokens int
	TotalTokens  int
	Model        string
}

// Provider 是一个 LLM 提供商的连接配置。
type Provider struct {
	Name      string // xiaomi / zhipu / openai
	BaseURL   string // e.g. https://api.xiaomi.com/v1
	APIKey    string
	Model     string // 默认模型
	ModelDeep string // 深度模型（可选）
}

// Client 是 LLM 调用客户端。
type Client struct {
	Providers  map[string]*Provider
	Default    string // 默认 provider 名
	HTTPClient *http.Client
	maxRetries int
}

// NewClient 创建 LLM 客户端。
func NewClient() *Client {
	return &Client{
		Providers:  map[string]*Provider{},
		HTTPClient: &http.Client{Timeout: 120 * time.Second},
		maxRetries: 2,
	}
}

// RegisterProvider 注册一个 LLM provider。
func (c *Client) RegisterProvider(p *Provider) {
	c.Providers[p.Name] = p
	if c.Default == "" {
		c.Default = p.Name
	}
}

// SetDefault 设置默认 provider。
func (c *Client) SetDefault(name string) { c.Default = name }

// GetProvider 获取指定 provider（空名返回默认）。
func (c *Client) GetProvider(name string) (*Provider, error) {
	if name == "" {
		name = c.Default
	}
	p, ok := c.Providers[name]
	if !ok {
		return nil, fmt.Errorf("provider %q 未注册", name)
	}
	return p, nil
}

// Complete 发送 chat completion（非流式——内部用流式接收但聚合返回）。
func (c *Client) Complete(providerName, model string, messages []Message, tools []Tool) (*CompletionResponse, error) {
	provider, err := c.GetProvider(providerName)
	if err != nil {
		return nil, err
	}
	if model == "" {
		model = provider.Model
	}

	reqBody := CompletionRequest{
		Model:    model,
		Messages: messages,
		Stream:   true, // 统一走 SSE（大多数 provider 非 stream 不返回 usage）
		Tools:    tools,
	}
	body, err := json.Marshal(reqBody)
	if err != nil {
		return nil, fmt.Errorf("marshal: %w", err)
	}

	var lastErr error
	for attempt := 0; attempt <= c.maxRetries; attempt++ {
		if attempt > 0 {
			time.Sleep(time.Duration(1<<uint(attempt-1)) * time.Second) // 指数退避
		}

		req, err := http.NewRequest("POST", provider.BaseURL+"/chat/completions", bytes.NewReader(body))
		if err != nil {
			return nil, err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+provider.APIKey)

		resp, err := c.HTTPClient.Do(req)
		if err != nil {
			lastErr = fmt.Errorf("HTTP 请求失败: %w", err)
			continue
		}

		if resp.StatusCode >= 400 {
			body, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			lastErr = fmt.Errorf("LLM API %d: %s", resp.StatusCode, string(body[:min(len(body), 300)]))
			if resp.StatusCode == 429 || resp.StatusCode >= 500 {
				continue // 可重试
			}
			return nil, lastErr
		}
		defer resp.Body.Close()

		result, err := parseSSE(resp.Body, model)
		if err != nil {
			lastErr = err
			continue
		}
		result.Model = model
		return result, nil
	}
	return nil, fmt.Errorf("重试 %d 次后仍失败: %w", c.maxRetries, lastErr)
}

// CompleteJSON 发送 chat completion 并解析 JSON 响应（skim/deep_dive 等）。
func (c *Client) CompleteJSON(providerName, model, prompt, stage string) (*CompletionResponse, error) {
	messages := []Message{
		{Role: "user", Content: "请只输出单个 JSON 对象，不要输出 markdown 代码块包裹，不要输出额外解释。\n\n" + prompt},
	}
	resp, err := c.Complete(providerName, model, messages, nil)
	if err != nil {
		return nil, err
	}
	return resp, nil
}

// SSEChunk 是 OpenAI streaming 的一个 SSE data 块。
type SSEChunk struct {
	ID      string `json:"id"`
	Choices []struct {
		Delta struct {
			Role      string `json:"role,omitempty"`
			Content   string `json:"content,omitempty"`
			ToolCalls []struct {
				Index    int    `json:"index"`
				ID       string `json:"id,omitempty"`
				Type     string `json:"type,omitempty"`
				Function struct {
					Name      string `json:"name,omitempty"`
					Arguments string `json:"arguments,omitempty"`
				} `json:"function"`
			} `json:"tool_calls,omitempty"`
		} `json:"delta"`
		FinishReason *string `json:"finish_reason"`
	} `json:"choices"`
	Usage *struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		TotalTokens      int `json:"total_tokens"`
	} `json:"usage,omitempty"`
}

// parseSSE 解析 OpenAI streaming SSE 响应并聚合为 CompletionResponse。
func parseSSE(r io.Reader, model string) (*CompletionResponse, error) {
	result := &CompletionResponse{Model: model}
	toolCallsByIndex := map[int]*ToolCall{}

	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024) // 1MB max line
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		data := strings.TrimPrefix(line, "data: ")
		if data == "[DONE]" {
			break
		}

		var chunk SSEChunk
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			continue // 跳过不可解析的行
		}

		// usage（最后一个 chunk 携带）
		if chunk.Usage != nil {
			result.InputTokens = chunk.Usage.PromptTokens
			result.OutputTokens = chunk.Usage.CompletionTokens
			result.TotalTokens = chunk.Usage.TotalTokens
		}

		for _, choice := range chunk.Choices {
			if choice.FinishReason != nil && *choice.FinishReason != "" {
				result.FinishReason = *choice.FinishReason
			}
			delta := choice.Delta
			if delta.Content != "" {
				result.Content += delta.Content
			}
			for _, tc := range delta.ToolCalls {
				existing, ok := toolCallsByIndex[tc.Index]
				if !ok {
					existing = &ToolCall{ID: tc.ID, Type: tc.Type}
					toolCallsByIndex[tc.Index] = existing
				}
				if tc.Function.Name != "" {
					existing.Function.Name = tc.Function.Name
				}
				if tc.Function.Arguments != "" {
					existing.Function.Arguments += tc.Function.Arguments
				}
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("SSE read: %w", err)
	}

	// 聚合 tool_calls（按 index 排序）
	for i := 0; i < len(toolCallsByIndex); i++ {
		if tc, ok := toolCallsByIndex[i]; ok {
			result.ToolCalls = append(result.ToolCalls, *tc)
		}
	}

	return result, nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
