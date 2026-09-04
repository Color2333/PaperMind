// Go Executor 计算层（Phase 2）：skim/deep_read/embed 纯计算——返回 proposal 不写领域表。
// 领域 apply 由 Go 权威面 ApplyResult 单事务完成。
package core

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/Color2333/PaperMind/core/llm"
)

// PipelineExecutor 执行 A 档 capability 的纯计算（proposal 模式）。
type PipelineExecutor struct {
	LLM      *llm.Client
	Provider string // 默认 provider 名
}

// NewPipelineExecutor 创建计算执行器。
func NewPipelineExecutor(llmClient *llm.Client, provider string) *PipelineExecutor {
	return &PipelineExecutor{LLM: llmClient, Provider: provider}
}

// SkimProposal 执行 skim 纯计算：读论文 → 构建 prompt → LLM → 结构化 skim report。
func (e *PipelineExecutor) SkimProposal(paperID string, title, abstract string) (map[string]any, error) {
	prompt := fmt.Sprintf(
		"请阅读以下论文并输出 JSON 对象（包含 one_liner, innovations(数组), keywords(数组), title_zh, abstract_zh, relevance_score(0-1浮点)）。\n\n标题: %s\n\n摘要: %s",
		title, abstract)

	provider, err := e.LLM.GetProvider(e.Provider)
	if err != nil {
		return nil, err
	}

	result, err := e.LLM.CompleteJSON(e.Provider, provider.Model, prompt, "skim")
	if err != nil {
		return nil, fmt.Errorf("LLM skim call: %w", err)
	}

	// 解析 LLM JSON 输出
	skim := parseLLMJSON(result.Content)
	if skim == nil {
		return nil, fmt.Errorf("skim LLM 输出非 JSON: %s", truncate(result.Content, 200))
	}

	return map[string]any{
		"proposal": map[string]any{
			"kind":     "skim_paper",
			"paper_id": paperID,
			"skim":     skim,
			"trace": map[string]any{
				"stage": "skim", "paper_id": paperID,
				"provider": e.Provider, "model": provider.Model,
				"prompt_digest":  truncate(prompt, 500),
				"input_tokens":   result.InputTokens,
				"output_tokens":  result.OutputTokens,
				"total_cost_usd": 0.0,
			},
		},
	}, nil
}

// DeepDiveProposal 执行 deep read 纯计算：读论文+PDF → LLM → 结构化 deep report。
// PDF 路径由调用方提供（下载已在 claim 前完成——幂等基础设施写入）。
func (e *PipelineExecutor) DeepDiveProposal(paperID, title, sourceText string) (map[string]any, error) {
	prompt := fmt.Sprintf(
		"请深度阅读以下论文并输出 JSON 对象（包含 method_summary, experiments_summary, ablation_summary, reviewer_risks(数组)）。\n\n标题: %s\n\n内容: %s",
		title, truncate(sourceText, 8000))

	provider, err := e.LLM.GetProvider(e.Provider)
	if err != nil {
		return nil, err
	}

	result, err := e.LLM.CompleteJSON(e.Provider, provider.ModelDeep, prompt, "deep")
	if err != nil {
		return nil, fmt.Errorf("LLM deep call: %w", err)
	}

	deep := parseLLMJSON(result.Content)
	if deep == nil {
		return nil, fmt.Errorf("deep LLM 输出非 JSON: %s", truncate(result.Content, 200))
	}

	return map[string]any{
		"proposal": map[string]any{
			"kind":     "deep_read_paper",
			"paper_id": paperID,
			"deep":     deep,
			"trace": map[string]any{
				"stage": "deep_dive", "paper_id": paperID,
				"provider": e.Provider, "model": provider.ModelDeep,
				"prompt_digest":  truncate(prompt, 500),
				"input_tokens":   result.InputTokens,
				"output_tokens":  result.OutputTokens,
				"total_cost_usd": 0.0,
			},
		},
	}, nil
}

// EmbedProposal 执行 embed 纯计算：构建文本 → LLM embed → 返回向量。
func (e *PipelineExecutor) EmbedProposal(paperID, title, abstract string) (map[string]any, error) {
	content := title + "\n" + abstract

	provider, err := e.LLM.GetProvider(e.Provider)
	if err != nil {
		return nil, err
	}

	// Embedding 走独立 API（不同 endpoint/model）
	_ = provider
	vector, err := e.LLM.Embed(e.Provider, content)
	if err != nil {
		return nil, fmt.Errorf("embed call: %w", err)
	}

	return map[string]any{
		"proposal": map[string]any{
			"kind":     "embed_paper",
			"paper_id": paperID,
			"vector":   vector,
		},
	}, nil
}

// parseLLMJSON 从 LLM 输出中提取 JSON 对象（去除 markdown 包裹等）。
func parseLLMJSON(content string) map[string]any {
	content = strings.TrimSpace(content)
	// 去除 markdown 代码块
	if idx := strings.Index(content, "{"); idx >= 0 {
		end := strings.LastIndex(content, "}")
		if end > idx {
			content = content[idx : end+1]
		}
	}
	var result map[string]any
	if err := jsonParse(content, &result); err != nil {
		return nil
	}
	return result
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}

// jsonParse 是 json.Unmarshal 的别名（避免直接依赖）。
func jsonParse(data string, v any) error {
	return json.Unmarshal([]byte(data), v)
}
