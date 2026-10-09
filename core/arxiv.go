// arXiv 客户端：Atom API 检索 + PDF 下载 + CS 分类。
//
// 与 Python ArxivClient 语义对齐：查询语法构造、429/500 退避重试、
// 速率间隔（3s）；PDF 404 → PdfUnavailableError（永久条件，调用方打标）。
package core

import (
	"context"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// PdfUnavailableError 永久性条件：arXiv 无此 PDF（调用方标记 pdf_unavailable 后不再重试）。
var PdfUnavailableError = errors.New("arxiv pdf unavailable")

const arxivAPIURL = "https://export.arxiv.org/api/query"

// ArxivClient arXiv API 客户端。
type ArxivClient struct {
	http *http.Client
}

// NewArxivClient 构建客户端。
func NewArxivClient() *ArxivClient {
	return &ArxivClient{http: &http.Client{Timeout: 60 * time.Second}}
}

// ArxivPaper 检索结果条目（字段与 ingest proposal 的 paper item 对齐）。
type ArxivPaper struct {
	ArxivID         string         `json:"arxiv_id"`
	Title           string         `json:"title"`
	Abstract        string         `json:"abstract"`
	PublicationDate string         `json:"publication_date,omitempty"`
	Source          string         `json:"source,omitempty"`
	SourceID        string         `json:"source_id,omitempty"`
	DOI             string         `json:"doi,omitempty"`
	Metadata        map[string]any `json:"metadata,omitempty"`
}

// BuildArxivQuery 查询语法构造（Python _build_arxiv_query 移植）。
func BuildArxivQuery(raw string, daysBack int) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return raw
	}
	dateFilter := ""
	if daysBack > 0 {
		from := time.Now().UTC().AddDate(0, 0, -daysBack).Format("20060102")
		dateFilter = fmt.Sprintf(" AND submittedDate:[%s000000 TO *]", from)
	}
	structuredRe := regexp.MustCompile(`\b(all|ti|au|abs|cat|co|jr|rn|id):`)
	if structuredRe.MatchString(raw) {
		if !strings.Contains(raw, "submittedDate:") {
			return raw + dateFilter
		}
		return raw
	}
	if m := regexp.MustCompile(`^"(.+)"$`).FindStringSubmatch(raw); m != nil {
		return fmt.Sprintf(`all:"%s"`, strings.TrimSpace(m[1])) + dateFilter
	}
	var tokens []string
	for _, t := range strings.Fields(raw) {
		if len([]rune(t)) >= 2 {
			tokens = append(tokens, t)
		}
		if len(tokens) >= 6 {
			break
		}
	}
	if len(tokens) == 0 {
		return "all:" + raw
	}
	ands := make([]string, len(tokens))
	for i, t := range tokens {
		ands[i] = "all:" + t
	}
	return strings.Join(ands, " AND ") + dateFilter
}

// fetchWithRetry 带 429/超时退避的 GET（与 Python 三次重试语义对齐）。
func (a *ArxivClient) fetchWithRetry(ctx context.Context, params url.Values) (string, error) {
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 {
			time.Sleep(time.Duration(3*(attempt+1)) * time.Second)
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, arxivAPIURL+"?"+params.Encode(), nil)
		if err != nil {
			return "", err
		}
		req.Header.Set("User-Agent", "PaperMind/2.0 (Go worker)")
		resp, err := a.http.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 32<<20))
		resp.Body.Close()
		if resp.StatusCode == 429 {
			lastErr = fmt.Errorf("arxiv 429 限流")
			continue
		}
		if resp.StatusCode != http.StatusOK {
			return "", fmt.Errorf("arxiv %d: %s", resp.StatusCode, truncateStr(string(raw), 200))
		}
		return string(raw), nil
	}
	return "", lastErr
}

type atomFeed struct {
	XMLName xml.Name    `xml:"feed"`
	Entries []atomEntry `xml:"entry"`
}

type atomEntry struct {
	ID        string `xml:"id"`
	Title     string `xml:"title"`
	Summary   string `xml:"summary"`
	Published string `xml:"published"`
	Authors   []struct {
		Name string `xml:"name"`
	} `xml:"author"`
	Categories []struct {
		Term string `xml:"term,attr"`
	} `xml:"category"`
}

// FetchLatest 关键词检索（分页由调用方控制 start）。
func (a *ArxivClient) FetchLatest(ctx context.Context, query string, maxResults, start, daysBack int, sortBy string) ([]ArxivPaper, error) {
	structured := BuildArxivQuery(query, daysBack)
	params := url.Values{
		"search_query": {structured},
		"sortBy":       {sortBy},
		"sortOrder":    {"descending"},
		"start":        {strconv.Itoa(start)},
		"max_results":  {strconv.Itoa(maxResults)},
	}
	raw, err := a.fetchWithRetry(ctx, params)
	if err != nil {
		return nil, err
	}
	return parseAtom(raw)
}

// FetchByIDs 按 ID 批量获取元数据。
func (a *ArxivClient) FetchByIDs(ctx context.Context, arxivIDs []string) ([]ArxivPaper, error) {
	if len(arxivIDs) == 0 {
		return nil, nil
	}
	clean := make([]string, len(arxivIDs))
	for i, id := range arxivIDs {
		clean[i] = strings.Split(id, "v")[0]
	}
	params := url.Values{"id_list": {strings.Join(clean, ",")}, "max_results": {strconv.Itoa(len(clean))}}
	raw, err := a.fetchWithRetry(ctx, params)
	if err != nil {
		return nil, err
	}
	return parseAtom(raw)
}

func parseAtom(raw string) ([]ArxivPaper, error) {
	var feed atomFeed
	if err := xml.Unmarshal([]byte(raw), &feed); err != nil {
		return nil, fmt.Errorf("arxiv atom 解析失败: %w", err)
	}
	papers := make([]ArxivPaper, 0, len(feed.Entries))
	for _, entry := range feed.Entries {
		id := strings.TrimSpace(entry.ID)
		if id == "" {
			continue
		}
		parts := strings.Split(id, "/")
		arxivID := parts[len(parts)-1]
		title := strings.Join(strings.Fields(entry.Title), " ")
		summary := strings.TrimSpace(entry.Summary)
		pubDate := ""
		if t, err := time.Parse(time.RFC3339, strings.TrimSpace(entry.Published)); err == nil {
			pubDate = t.Format("2006-01-02")
		}
		cats := make([]string, 0, len(entry.Categories))
		for _, c := range entry.Categories {
			if c.Term != "" {
				cats = append(cats, c.Term)
			}
		}
		authors := make([]string, 0, len(entry.Authors))
		for _, au := range entry.Authors {
			if au.Name != "" {
				authors = append(authors, au.Name)
			}
		}
		meta := map[string]any{"source": "arxiv", "categories": cats, "authors": authors}
		if len(cats) > 0 {
			meta["primary_category"] = cats[0]
		}
		papers = append(papers, ArxivPaper{
			ArxivID:         arxivID,
			Title:           title,
			Abstract:        summary,
			PublicationDate: pubDate,
			Source:          "arxiv",
			SourceID:        arxivID,
			Metadata:        meta,
		})
	}
	return papers, nil
}

// DownloadPDF 下载论文 PDF 到存储根目录，返回绝对路径。
func (a *ArxivClient) DownloadPDF(ctx context.Context, arxivID, pdfRoot string) (string, error) {
	target := filepath.Join(pdfRoot, arxivID+".pdf")
	if fi, err := os.Stat(target); err == nil && fi.Size() > 0 {
		return target, nil // 幂等：已存在直接复用
	}
	if err := os.MkdirAll(pdfRoot, 0o755); err != nil {
		return "", err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://arxiv.org/pdf/"+arxivID+".pdf", nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "PaperMind/2.0 (Go worker)")
	resp, err := a.http.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 404 {
		return "", fmt.Errorf("%w: %s (404)", PdfUnavailableError, arxivID)
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("arxiv pdf %d: %s", resp.StatusCode, arxivID)
	}
	tmp := target + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return "", err
	}
	if _, err = io.Copy(f, resp.Body); err != nil {
		f.Close()
		os.Remove(tmp)
		return "", err
	}
	if err = f.Close(); err != nil {
		os.Remove(tmp)
		return "", err
	}
	if err = os.Rename(tmp, target); err != nil {
		os.Remove(tmp)
		return "", err
	}
	return target, nil
}

// FetchCSCategories arXiv 分类页解析失败时回退常用 CS 清单（与 Python 语义对齐）。
func (a *ArxivClient) FetchCSCategories(ctx context.Context) []map[string]string {
	fallback := []map[string]string{
		{"code": "cs.CV", "name": "Computer Vision and Pattern Recognition"},
		{"code": "cs.LG", "name": "Machine Learning"},
		{"code": "cs.CL", "name": "Computation and Language"},
		{"code": "cs.AI", "name": "Artificial Intelligence"},
		{"code": "cs.NE", "name": "Neural and Evolutionary Computing"},
		{"code": "cs.IR", "name": "Information Retrieval"},
		{"code": "cs.IT", "name": "Information Theory"},
		{"code": "cs.CR", "name": "Cryptography and Security"},
		{"code": "cs.DS", "name": "Data Structures and Algorithms"},
		{"code": "cs.DB", "name": "Databases"},
		{"code": "cs.DC", "name": "Distributed Computing"},
		{"code": "cs.SE", "name": "Software Engineering"},
		{"code": "cs.PL", "name": "Programming Languages"},
		{"code": "cs.HC", "name": "Human-Computer Interaction"},
		{"code": "cs.GR", "name": "Graphics"},
		{"code": "cs.RO", "name": "Robotics"},
		{"code": "cs.CY", "name": "Computers and Society"},
		{"code": "cs.SI", "name": "Social and Information Networks"},
		{"code": "cs.MA", "name": "Multiagent Systems"},
		{"code": "cs.MM", "name": "Multimedia"},
		{"code": "cs.OH", "name": "Other"},
	}
	// Python 版即直接返回内置清单（网络分类页解析已弃用）——保持一致
	return fallback
}

// MarkPDFUnavailable 永久标记（download_source / deep_read 的 404 路径共用）。
func MarkPDFUnavailable(store *CoreStore, paperID, reason string) {
	meta := map[string]any{}
	var raw []byte
	if err := store.DB.QueryRow(`SELECT metadata FROM papers WHERE id=$1`, paperID).Scan(&raw); err == nil {
		_ = json.Unmarshal(raw, &meta)
	}
	meta["pdf_unavailable"] = true
	meta["pdf_unavailable_reason"] = reason
	_, _ = store.DB.Exec(`UPDATE papers SET metadata=$1 WHERE id=$2`, mustJSON(meta), paperID)
}
