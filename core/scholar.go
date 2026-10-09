// Semantic Scholar 客户端：论文定位 + 引用边抓取（引用图谱数据源）。
//
// 与 Python SemanticScholarClient 语义对齐：ARXIV: 前缀直查 → 标题搜索回退；
// 429/5xx 指数退避（2/4/8s）；404 返回 nil（不算错误）。
package core

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"time"
)

// ScholarClient S2 API 客户端。
type ScholarClient struct {
	baseURL string
	apiKey  string
	http    *http.Client
}

// NewScholarClient 从环境构建（S2_API_KEY 可选）。
func NewScholarClient() *ScholarClient {
	return &ScholarClient{
		baseURL: "https://api.semanticscholar.org/graph/v1",
		apiKey:  os.Getenv("S2_API_KEY"),
		http:    &http.Client{Timeout: 30 * time.Second},
	}
}

// get 带 429/5xx 退避的 GET；404 → nil, nil。
func (s *ScholarClient) get(ctx context.Context, path string, params url.Values) (map[string]any, error) {
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 {
			time.Sleep(time.Duration(1<<uint(attempt)) * time.Second) // 2/4/8s
		}
		u := s.baseURL + path
		if len(params) > 0 {
			u += "?" + params.Encode()
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
		if err != nil {
			return nil, err
		}
		if s.apiKey != "" {
			req.Header.Set("x-api-key", s.apiKey)
		}
		resp, err := s.http.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
		resp.Body.Close()
		if resp.StatusCode == 404 {
			return nil, nil
		}
		if resp.StatusCode == 429 || resp.StatusCode >= 500 {
			lastErr = fmt.Errorf("s2 %d", resp.StatusCode)
			continue
		}
		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("s2 %d: %s", resp.StatusCode, truncateStr(string(raw), 200))
		}
		var out map[string]any
		if err := json.Unmarshal(raw, &out); err != nil {
			return nil, err
		}
		return out, nil
	}
	return nil, lastErr
}

// ResolvePaperID 定位 S2 paperId：arxiv_id 直查 → 标题搜索。
func (s *ScholarClient) ResolvePaperID(ctx context.Context, arxivID, title string) (string, error) {
	if arxivID != "" {
		clean := strings.Split(arxivID, "v")[0]
		data, err := s.get(ctx, "/paper/ARXIV:"+clean, url.Values{"fields": {"paperId"}})
		if err != nil {
			return "", err
		}
		if data != nil {
			if id, ok := data["paperId"].(string); ok && id != "" {
				return id, nil
			}
		}
	}
	if title == "" {
		return "", nil
	}
	data, err := s.get(ctx, "/paper/search", url.Values{"query": {title}, "limit": {"1"}, "fields": {"title"}})
	if err != nil {
		return "", err
	}
	if data == nil {
		return "", nil
	}
	if dataList, ok := data["data"].([]any); ok && len(dataList) > 0 {
		if first, ok := dataList[0].(map[string]any); ok {
			if id, ok := first["paperId"].(string); ok {
				return id, nil
			}
		}
	}
	return "", nil
}

// CitationEdge 引用边候选（source 引用 target 语义由 context 区分：reference/citation）。
type CitationEdge struct {
	SourceTitle string `json:"source_title"`
	TargetTitle string `json:"target_title"`
	Context     string `json:"context"`
}

// FetchEdgesByTitle 按标题抓取引用边候选（references + citations 各取 limit）。
func (s *ScholarClient) FetchEdgesByTitle(ctx context.Context, title string, limit int) ([]CitationEdge, error) {
	title = strings.TrimSpace(title)
	if title == "" {
		return nil, nil
	}
	paperID, err := s.ResolvePaperID(ctx, "", title)
	if err != nil || paperID == "" {
		return nil, err
	}
	payload, err := s.get(ctx, "/paper/"+paperID, url.Values{"fields": {"references.title,citations.title"}})
	if err != nil || payload == nil {
		return nil, err
	}
	edges := []CitationEdge{}
	n := 0
	if refs, ok := payload["references"].([]any); ok {
		for _, r := range refs {
			if n >= limit {
				break
			}
			m, ok := r.(map[string]any)
			if !ok {
				continue
			}
			t := strings.TrimSpace(stringOf(m["title"]))
			if t == "" {
				continue
			}
			edges = append(edges, CitationEdge{SourceTitle: title, TargetTitle: t, Context: "reference"})
			n++
		}
	}
	n = 0
	if cits, ok := payload["citations"].([]any); ok {
		for _, c := range cits {
			if n >= limit {
				break
			}
			m, ok := c.(map[string]any)
			if !ok {
				continue
			}
			t := strings.TrimSpace(stringOf(m["title"]))
			if t == "" {
				continue
			}
			edges = append(edges, CitationEdge{SourceTitle: t, TargetTitle: title, Context: "citation"})
			n++
		}
	}
	return edges, nil
}

// titleToID 标题 → 归一化合成键（Python _title_to_id 移植：ss-<slug48>）。
func titleToID(title string) string {
	reg := regexp.MustCompile(`[^a-zA-Z0-9]+`)
	slug := reg.ReplaceAllString(strings.ToLower(strings.TrimSpace(title)), "-")
	slug = strings.Trim(slug, "-")
	if len(slug) > 48 {
		slug = slug[:48]
	}
	return "ss-" + slug
}

func stringOf(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
