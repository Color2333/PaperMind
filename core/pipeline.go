// Go Executor 计算层：仅保留无 LLM 的纯计算/基础设施 proposal（fetch/upsert/download）。
// LLM 类能力（skim/deep_read/embed/extract_claims）统一由 Python Executor（AI 栈）领取，
// 计算后回传 proposal，Go 权威面 ApplyResult 单事务落库——LLM 网关不在 Go 侧复刻。
package core

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// PipelineExecutor 执行无 LLM capability 的纯计算（proposal 模式）。
type PipelineExecutor struct{}

// NewPipelineExecutor 创建计算执行器。
func NewPipelineExecutor() *PipelineExecutor {
	return &PipelineExecutor{}
}

// FetchProposal 调用 arXiv API 搜索论文候选（纯计算——不写领域表）。
// 返回候选列表供 workflow fan-out 使用。
func (e *PipelineExecutor) FetchProposal(query string, maxResults int) (map[string]any, error) {
	arxivURL := fmt.Sprintf(
		"http://export.arxiv.org/api/query?search_query=all:%s&max_results=%d&sortBy=submittedDate",
		url.QueryEscape(query), maxResults)

	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Get(arxivURL)
	if err != nil {
		return nil, fmt.Errorf("arXiv API: %w", err)
	}
	defer resp.Body.Close()

	// 解析 Atom XML → 简化：提取 title/summary/arxiv_id
	body, _ := io.ReadAll(resp.Body)
	var papers []map[string]any
	for _, entry := range strings.Split(string(body), "<entry>")[1:] {
		title := extractXMLField(entry, "title")
		summary := extractXMLField(entry, "summary")
		idURL := extractXMLField(entry, "id")
		arxivID := ""
		if idx := strings.LastIndex(idURL, "/"); idx >= 0 {
			arxivID = idURL[idx+1:]
		}
		if title != "" && arxivID != "" {
			papers = append(papers, map[string]any{
				"arxiv_id": arxivID, "title": title, "abstract": summary,
			})
		}
	}

	return map[string]any{
		"candidates": papers,
		"total":      len(papers),
	}, nil
}

func extractXMLField(xml, field string) string {
	start := strings.Index(xml, "<"+field+">")
	if start == -1 {
		return ""
	}
	start += len(field) + 2
	end := strings.Index(xml[start:], "</"+field+">")
	if end == -1 {
		return ""
	}
	return strings.TrimSpace(xml[start : start+end])
}

// UpsertProposal 论文 upsert（Go SQL——写入 papers + source_versions）。
// 由 ApplyResult 的 upsert_paper 分支执行（非纯计算——直接写 DB）。
func (e *PipelineExecutor) UpsertProposal(arxivID, title, abstract string) (map[string]any, error) {
	// 领域写入在 ApplyResult 中执行——此处只返回 proposal
	return map[string]any{
		"proposal": map[string]any{
			"kind":     "upsert_paper",
			"arxiv_id": arxivID,
			"title":    title,
			"abstract": abstract,
		},
	}, nil
}

// DownloadProposal 下载 PDF（幂等基础设施写入——文件落盘 + set_pdf_path）。
func (e *PipelineExecutor) DownloadProposal(arxivID string) (map[string]any, error) {
	// PDF 下载由 arXiv API（HTTP GET）——文件写入到本地存储
	pdfURL := fmt.Sprintf("https://arxiv.org/pdf/%s.pdf", arxivID)
	return map[string]any{
		"proposal": map[string]any{
			"kind":     "download_source",
			"arxiv_id": arxivID,
			"pdf_url":  pdfURL,
		},
	}, nil
}
