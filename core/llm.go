// LLM 客户端：Pi 网关（OpenAI 兼容面）chat + embedding。
//
// 与 Python LLMClient 的网关路径语义对齐：model 传 "skim"/"deep" 语义名，
// 由网关解析真实模型；embedding 走独立 provider（SiliconFlow bge-m3 等）。
package core

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"
)

// GatewayClient Pi 网关 OpenAI 兼容客户端。
type GatewayClient struct {
	baseURL string
	token   string
	http    *http.Client
}

// NewGatewayClient 从环境构建（PAPERMIND_GATEWAY_URL / PAPERMIND_GATEWAY_TOKEN）。
func NewGatewayClient() *GatewayClient {
	base := os.Getenv("PAPERMIND_GATEWAY_URL")
	if base == "" {
		base = "http://gateway:8765"
	}
	tok := os.Getenv("PAPERMIND_GATEWAY_TOKEN")
	if tok == "" {
		tok = "pm-gateway-internal"
	}
	return &GatewayClient{
		baseURL: strings.TrimRight(base, "/"),
		token:   tok,
		http:    &http.Client{Timeout: 180 * time.Second},
	}
}

// gatewayChatResult chat 补全结果（usage 供 prompt_traces 成本观测）。
type gatewayChatResult struct {
	Content       string
	InputTokens   int
	OutputTokens  int
	ReasoningHint string // 部分网关在 reasoning_content 放 JSON
}

// Chat 单轮补全。model 为语义名（skim/deep）。
func (g *GatewayClient) Chat(ctx context.Context, model, prompt string, maxTokens int) (*gatewayChatResult, error) {
	body := map[string]any{
		"model":    model,
		"messages": []map[string]string{{"role": "user", "content": prompt}},
	}
	if maxTokens > 0 {
		body["max_tokens"] = maxTokens
	}
	payload, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, g.baseURL+"/v1/chat/completions", bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+g.token)
	resp, err := g.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("gateway %d: %s", resp.StatusCode, truncateStr(string(raw), 300))
	}
	var parsed struct {
		Choices []struct {
			Message struct {
				Content           string `json:"content"`
				ReasoningContent  string `json:"reasoning_content"`
				ReasoningContentB string `json:"reasoning"`
			} `json:"message"`
		} `json:"choices"`
		Usage struct {
			PromptTokens     int `json:"prompt_tokens"`
			CompletionTokens int `json:"completion_tokens"`
		} `json:"usage"`
	}
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return nil, fmt.Errorf("gateway 响应解析失败: %w", err)
	}
	if len(parsed.Choices) == 0 {
		return nil, errors.New("gateway 返回空 choices")
	}
	msg := parsed.Choices[0].Message
	reasoning := msg.ReasoningContent
	if reasoning == "" {
		reasoning = msg.ReasoningContentB
	}
	return &gatewayChatResult{
		Content:       msg.Content,
		InputTokens:   parsed.Usage.PromptTokens,
		OutputTokens:  parsed.Usage.CompletionTokens,
		ReasoningHint: reasoning,
	}, nil
}

// CompleteJSON 网关补全 + JSON 提取（与 Python complete_json 的包装/重试语义对齐）。
func (g *GatewayClient) CompleteJSON(ctx context.Context, model, prompt string) (map[string]any, *gatewayChatResult, error) {
	wrapped := "请只输出单个 JSON 对象，不要输出 markdown 代码块包裹，不要输出额外解释。\n" +
		"如果信息不足，请根据上下文给出最合理的保守估计，并保持 JSON 结构完整。\n\n" + prompt
	var last *gatewayChatResult
	for attempt := 0; attempt < 2; attempt++ {
		res, err := g.Chat(ctx, model, wrapped, 0)
		if err != nil {
			// 网络类错误一次退避重试
			if attempt == 0 && ctx.Err() == nil {
				time.Sleep(2 * time.Second)
				continue
			}
			return nil, nil, err
		}
		last = res
		if parsed := ParseLooseJSON(res.Content); parsed != nil {
			return parsed, res, nil
		}
		if res.ReasoningHint != "" {
			if parsed := ParseLooseJSON(res.ReasoningHint); parsed != nil {
				return parsed, res, nil
			}
		}
	}
	if last == nil {
		return nil, nil, errors.New("gateway 补全失败")
	}
	return nil, last, fmt.Errorf("JSON 解析最终失败, content[:200]=%s", truncateStr(last.Content, 200))
}

var (
	fenceRe  = regexp.MustCompile("(?s)```[a-zA-Z]*\\s*(.*?)```")
	trailRe  = regexp.MustCompile(",\\s*([}\\]])")
	bracesRe = regexp.MustCompile(`\{`)
)

// ParseLooseJSON 宽松 JSON 提取：剥 markdown 围栏 → 大括号扫描 → 尾逗号清理。
func ParseLooseJSON(text string) map[string]any {
	text = strings.TrimSpace(text)
	if text == "" {
		return nil
	}
	candidates := []string{text}
	if m := fenceRe.FindStringSubmatch(text); m != nil {
		candidates = append(candidates, strings.TrimSpace(m[1]))
	}
	// 从每个 { 起贪婪扫描到配对 }（宽松场景下取最深嵌套候选）
	if idx := strings.Index(text, "{"); idx >= 0 {
		candidates = append(candidates, text[idx:])
	}
	for _, cand := range candidates {
		if obj := tryUnmarshalObject(cand); obj != nil {
			return obj
		}
		if obj := tryUnmarshalObject(trailRe.ReplaceAllString(cand, "$1")); obj != nil {
			return obj
		}
	}
	return nil
}

func tryUnmarshalObject(s string) map[string]any {
	// 找到与首个 { 配对的 }（忽略字符串内的括号）
	depth, inStr, esc := 0, false, false
	end := -1
	for i, ch := range s {
		if esc {
			esc = false
			continue
		}
		switch {
		case ch == '\\' && inStr:
			esc = true
		case ch == '"':
			inStr = !inStr
		case inStr:
		case ch == '{':
			depth++
		case ch == '}':
			depth--
			if depth == 0 {
				end = i + 1
			}
		}
		if end > 0 {
			break
		}
	}
	if end <= 0 {
		return nil
	}
	var obj map[string]any
	if err := json.Unmarshal([]byte(s[:end]), &obj); err != nil {
		return nil
	}
	return obj
}

// ---------- Embedding ----------

// EmbedClient OpenAI 兼容 embeddings 客户端（SiliconFlow / DashScope 等）。
type EmbedClient struct {
	baseURL    string
	apiKey     string
	model      string
	dimensions int
	http       *http.Client
}

// NewEmbedClient 环境变量：EMBEDDING_API_KEY / EMBEDDING_BASE_URL /
// EMBEDDING_MODEL / EMBEDDING_DIMENSIONS。未配置返回 nil（调用方报错）。
func NewEmbedClient() *EmbedClient {
	key := os.Getenv("EMBEDDING_API_KEY")
	if key == "" {
		return nil
	}
	base := os.Getenv("EMBEDDING_BASE_URL")
	if base == "" {
		base = "https://api.siliconflow.cn/v1"
	}
	model := os.Getenv("EMBEDDING_MODEL")
	if model == "" {
		model = "BAAI/bge-m3"
	}
	dims := 0
	if d := os.Getenv("EMBEDDING_DIMENSIONS"); d != "" {
		fmt.Sscanf(d, "%d", &dims)
	}
	return &EmbedClient{
		baseURL:    strings.TrimRight(base, "/"),
		apiKey:     key,
		model:      model,
		dimensions: dims,
		http:       &http.Client{Timeout: 60 * time.Second},
	}
}

// Embed 单文本向量化。
func (e *EmbedClient) Embed(ctx context.Context, text string) ([]float64, error) {
	if e == nil {
		return nil, errors.New("embedding 未配置（EMBEDDING_API_KEY 缺失）")
	}
	if strings.TrimSpace(text) == "" {
		return nil, errors.New("embedding 输入为空")
	}
	body := map[string]any{"model": e.model, "input": text}
	if e.dimensions > 0 {
		body["dimensions"] = e.dimensions
	}
	payload, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, e.baseURL+"/embeddings", bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+e.apiKey)
	resp, err := e.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("embedding %d: %s", resp.StatusCode, truncateStr(string(raw), 300))
	}
	var parsed struct {
		Data []struct {
			Embedding []float64 `json:"embedding"`
		} `json:"data"`
	}
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return nil, err
	}
	if len(parsed.Data) == 0 || len(parsed.Data[0].Embedding) == 0 {
		return nil, errors.New("embedding 返回空向量")
	}
	return parsed.Data[0].Embedding, nil
}
