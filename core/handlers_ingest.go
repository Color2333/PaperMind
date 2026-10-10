// 摄入处理器：ingest_arxiv_query / import_selected / ingest_ieee /
// import_references / cs_feed_fetch_category / cs_feed_dispatch。
// 网络抓取 + 只读去重留 handler，领域写经 ingest_papers 系 proposal 单事务 apply。
package core

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// existingArxivIDs 已入库 arxiv_id 集合（只读去重）。
func existingArxivIDs(env *HandlerEnv, ids []string) (map[string]bool, error) {
	out := map[string]bool{}
	if len(ids) == 0 {
		return out, nil
	}
	ph := make([]string, len(ids))
	args := make([]any, len(ids))
	for i, id := range ids {
		ph[i] = fmt.Sprintf("$%d", i+1)
		args[i] = id
	}
	rows, err := env.Store.DB.Query(
		`SELECT arxiv_id FROM papers WHERE arxiv_id IN (`+strings.Join(ph, ",")+")", args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if rows.Scan(&id) == nil {
			out[id] = true
		}
	}
	return out, nil
}

// ingestProposal ingest_papers proposal 公共封装。
func ingestProposal(query string, papers []ArxivPaper, topicID, topicName, actionType, actionTitle string) map[string]any {
	items := make([]any, len(papers))
	for i, p := range papers {
		items[i] = paperItem(p)
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind": "ingest_papers", "query": query,
			"topic_id": topicID, "topic_name": topicName,
			"action_type": actionType, "action_title": actionTitle,
			"papers": items,
		},
	}
}

func paperItem(p ArxivPaper) map[string]any {
	return map[string]any{
		"arxiv_id": p.ArxivID, "title": p.Title, "abstract": p.Abstract,
		"publication_date": p.PublicationDate, "source": p.Source,
		"source_id": p.SourceID, "metadata": p.Metadata,
	}
}

// ---------- ingest_arxiv_query ----------

func HandleIngestArxivQuery(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	query, _ := task.Input["query"].(string)
	maxResults := intOf(task.Input["max_results"], 20)
	topicID, _ := task.Input["topic_id"].(string)
	sortBy, _ := task.Input["sort_by"].(string)
	if sortBy == "" {
		sortBy = "submittedDate"
	}
	daysBack := intOf(task.Input["days_back"], 0)
	actionType, _ := task.Input["action_type"].(string)
	if actionType == "" {
		actionType = "manual_collect"
	}
	if query == "" {
		return nil, errors.New("缺少 query")
	}

	// 分批递归抓取直到凑够 max_results 篇新论文（原语义）
	selected := make([]ArxivPaper, 0, maxResults)
	selectedIDs := map[string]bool{}
	const batchSize = 20
	const maxPages = 10
	for page := 0; page < maxPages && len(selected) < maxResults; page++ {
		start := page * batchSize
		needed := maxResults - len(selected)
		thisBatch := batchSize
		if needed+20 < thisBatch {
			thisBatch = needed + 20
		}
		papers, err := env.Arxiv.FetchLatest(ctx, query, thisBatch, start, daysBack, sortBy)
		if err != nil {
			return nil, err
		}
		if len(papers) == 0 {
			break
		}
		ids := make([]string, len(papers))
		for i, p := range papers {
			ids[i] = p.ArxivID
		}
		existing, err := existingArxivIDs(env, ids)
		if err != nil {
			return nil, err
		}
		for _, p := range papers {
			if !existing[p.ArxivID] && !selectedIDs[p.ArxivID] {
				selected = append(selected, p)
				selectedIDs[p.ArxivID] = true
				if len(selected) >= maxResults {
					break
				}
			}
		}
		if page < maxPages-1 {
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(3 * time.Second): // arxiv 限流间隔
			}
		}
	}
	return ingestProposal(query, selected, topicID, "", actionType, "收集："+truncateStr(query, 80)), nil
}

// ---------- import_selected ----------

func HandleImportSelected(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	ids := stringListOf(task.Input["arxiv_ids"])
	query, _ := task.Input["query"].(string)
	if len(ids) == 0 {
		return nil, errors.New("缺少 arxiv_ids")
	}
	selectedSet := map[string]bool{}
	for _, id := range ids {
		selectedSet[strings.Split(id, "v")[0]] = true
	}
	// 关键词检索 + 缺失补按 ID 抓取（原语义）
	var selected []ArxivPaper
	if query != "" {
		if papers, err := env.Arxiv.FetchLatest(ctx, query, 50, 0, 0, "submittedDate"); err == nil {
			for _, p := range papers {
				if selectedSet[p.ArxivID] {
					selected = append(selected, p)
				}
			}
		}
	}
	found := map[string]bool{}
	for _, p := range selected {
		found[p.ArxivID] = true
	}
	var missing []string
	for id := range selectedSet {
		if !found[id] {
			missing = append(missing, id)
		}
	}
	if len(missing) > 0 {
		if papers, err := env.Arxiv.FetchByIDs(ctx, missing); err == nil {
			selected = append(selected, papers...)
		}
	}
	return ingestProposal(query, selected, "", "", "agent_collect", "Agent 收集: "+truncateStr(query, 80)), nil
}

// ---------- ingest_ieee ----------

func HandleIngestIEEE(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	apiKey := envOr("IEEE_API_KEY", "")
	if apiKey == "" {
		return nil, errors.New("IEEE API Key 未配置，请设置 IEEE_API_KEY 环境变量")
	}
	query, _ := task.Input["query"].(string)
	maxResults := intOf(task.Input["max_results"], 20)
	topicID, _ := task.Input["topic_id"].(string)
	actionType, _ := task.Input["action_type"].(string)
	if actionType == "" {
		actionType = "manual_collect"
	}
	if query == "" {
		return nil, errors.New("缺少 query")
	}
	papers, err := FetchIEEE(ctx, apiKey, query, maxResults)
	if err != nil {
		return nil, err
	}
	// DOI / 合成键只读去重
	dois, keys := []string{}, []string{}
	for _, p := range papers {
		if p.DOI != "" {
			dois = append(dois, p.DOI)
		}
		if p.SourceID != "" {
			keys = append(keys, "ieee:"+p.SourceID)
		}
	}
	existingDois, err := existingArxivIDs(env, dois)
	if err != nil {
		return nil, err
	}
	existingKeys, err := existingArxivIDs(env, keys)
	if err != nil {
		return nil, err
	}
	selected := []ArxivPaper{}
	for _, p := range papers {
		if p.DOI != "" && existingDois[p.DOI] {
			continue
		}
		if p.SourceID != "" && existingKeys["ieee:"+p.SourceID] {
			continue
		}
		if p.SourceID != "" {
			p.ArxivID = "ieee:" + p.SourceID // 合成键：多源去重约定
		}
		selected = append(selected, p)
	}
	return ingestProposal(query, selected, topicID, "", actionType, "IEEE 收集："+truncateStr(query, 80)), nil
}

// fetchIEEE IEEE Xplore 检索（元数据，无 PDF——权限限制维持原状）。
func FetchIEEE(ctx context.Context, apiKey, query string, maxResults int) ([]ArxivPaper, error) {
	payload := map[string]any{
		"queryString": fmt.Sprintf(`("article_title":"%s" OR "abstract":"%s")`, query, query),
		"maxRecords":  maxResults,
		"startRecord": 1,
		"sortField":   "publication_date",
		"sortOrder":   "DESC",
		"searchField": "metadata",
	}
	raw, err := postJSON(ctx,
		"https://ieeexploreapi.ieee.org/api/v1/search/articles?apikey="+url.QueryEscape(apiKey),
		payload, 60*time.Second)
	if err != nil {
		return nil, err
	}
	var parsed struct {
		Articles []struct {
			DOI             string `json:"doi"`
			Title           string `json:"title"`
			Abstract        string `json:"abstract"`
			ArticleNum      string `json:"article_number"`
			PublicationDate string `json:"publication_date"`
		} `json:"articles"`
	}
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return nil, err
	}
	out := []ArxivPaper{}
	for _, a := range parsed.Articles {
		if a.Title == "" {
			continue
		}
		out = append(out, ArxivPaper{
			ArxivID:         "", // 合成键在调用方按 source_id 拼装
			Title:           a.Title,
			Abstract:        a.Abstract,
			PublicationDate: a.PublicationDate,
			Source:          "ieee",
			SourceID:        a.ArticleNum,
			DOI:             a.DOI,
			Metadata:        map[string]any{"source": "ieee"},
		})
	}
	return out, nil
}

// ---------- import_references ----------

func HandleImportReferences(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	sourcePaperID, _ := task.Input["source_paper_id"].(string)
	sourcePaperTitle, _ := task.Input["source_paper_title"].(string)
	entries, _ := task.Input["entries"].([]any)
	topics := stringListOf(task.Input["topic_ids"])
	if sourcePaperID == "" {
		return nil, errors.New("缺少 source_paper_id")
	}
	// 前置校验：源论文必须存在 + entries 非空（空批次在 apply 层会被拒——
	// 任务层重试到 dead_letter 只是噪音，快失败更干净）
	var exists string
	if err := env.Store.DB.QueryRow(`SELECT id FROM papers WHERE id=$1`, sourcePaperID).Scan(&exists); err != nil {
		return nil, fmt.Errorf("源论文 %s 不存在", sourcePaperID)
	}
	if len(entries) == 0 {
		return nil, errors.New("entries 为空——无参考文献可导入")
	}

	var arxivEntries, ssEntries []map[string]any
	for _, e := range entries {
		m, ok := e.(map[string]any)
		if !ok {
			continue
		}
		if stringOf(m["arxiv_id"]) != "" {
			arxivEntries = append(arxivEntries, m)
		} else {
			ssEntries = append(ssEntries, m)
		}
	}

	papers := []any{}
	skipped := 0
	if len(arxivEntries) > 0 {
		ids := make([]string, len(arxivEntries))
		for i, e := range arxivEntries {
			ids[i] = stringOf(e["arxiv_id"])
		}
		fetched := map[string]ArxivPaper{}
		if list, err := env.Arxiv.FetchByIDs(ctx, ids); err == nil {
			for _, p := range list {
				fetched[p.ArxivID] = p
			}
		}
		for _, e := range arxivEntries {
			p, ok := fetched[stringOf(e["arxiv_id"])]
			if !ok {
				skipped++
				continue
			}
			papers = append(papers, map[string]any{
				"paper": paperItem(p), "topics": topics,
				"direction": orDefault(stringOf(e["direction"]), "reference"),
			})
		}
	}
	for _, e := range ssEntries {
		paperDict := map[string]any{
			"arxiv_id": "", "title": orDefault(stringOf(e["title"]), "Unknown"),
			"abstract": "", "metadata": map[string]any{"source": "semantic_scholar"},
		}
		if sid := stringOf(e["scholar_id"]); sid != "" {
			detail, err := env.Scholar.get(ctx, "/paper/"+sid,
				url.Values{"fields": {"title,abstract,externalIds"}})
			if err == nil && detail != nil {
				extIDs, _ := detail["externalIds"].(map[string]any)
				arxivOf := ""
				if extIDs != nil {
					arxivOf = stringOf(extIDs["ArXiv"])
				}
				paperDict = map[string]any{
					"arxiv_id": arxivOf,
					"title":    orDefault(stringOf(detail["title"]), orDefault(stringOf(e["title"]), "Unknown")),
					"abstract": stringOf(detail["abstract"]),
					"metadata": map[string]any{"source": "semantic_scholar"},
				}
				time.Sleep(500 * time.Millisecond)
			}
		}
		papers = append(papers, map[string]any{
			"paper": paperDict, "topics": topics,
			"direction": orDefault(stringOf(e["direction"]), "reference"),
		})
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind":               "reference_import",
			"source_paper_id":    sourcePaperID,
			"source_paper_title": sourcePaperTitle,
			"papers":             papers,
		},
	}, nil
}

// ---------- cs_feed_fetch_category / cs_feed_dispatch ----------

func HandleCsFeedFetchCategory(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	categoryCode, _ := task.Input["category_code"].(string)
	if categoryCode == "" {
		return nil, errors.New("缺少 category_code")
	}
	var dailyLimit int
	err := env.Store.DB.QueryRow(
		`SELECT daily_limit FROM cs_feed_subscriptions WHERE category_code=$1`, categoryCode,
	).Scan(&dailyLimit)
	if err != nil {
		return nil, fmt.Errorf("订阅 %s 不存在", categoryCode)
	}
	if dailyLimit <= 0 {
		dailyLimit = 30
	}
	papers, err := env.Arxiv.FetchLatest(ctx, fmt.Sprintf("cat:%s", categoryCode), dailyLimit, 0, 7, "submittedDate")
	if err != nil {
		return nil, err
	}
	items := make([]any, len(papers))
	for i, p := range papers {
		items[i] = paperItem(p)
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind": "cs_feed_fetch", "category_code": categoryCode, "papers": items,
		},
	}, nil
}

// HandleCsFeedDispatch 分类表同步 proposal + 到点订阅逐个提交抓取任务
// （冷却/配额过滤留编排侧——与重设计语义一致；不等待子任务，无自死锁）。
func HandleCsFeedDispatch(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	cats := env.Arxiv.FetchCSCategories(ctx)
	catItems := make([]any, len(cats))
	for i, c := range cats {
		catItems[i] = map[string]any{"code": c["code"], "name": c["name"], "description": ""}
	}

	now := time.Now().UTC()
	todayStart := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	rows, err := env.Store.DB.Query(
		`SELECT category_code, status, cool_down_until, last_run_at, last_run_count, daily_limit
		 FROM cs_feed_subscriptions WHERE enabled = true`)
	if err != nil {
		return nil, err
	}
	type sub struct {
		code, status  string
		coolDownUntil *time.Time
		lastRunAt     *time.Time
		lastRunCount  int
		dailyLimit    int
	}
	var subs []sub
	for rows.Next() {
		var s sub
		var coolDown, lastRun sql.NullTime
		if err := rows.Scan(&s.code, &s.status, &coolDown, &lastRun, &s.lastRunCount, &s.dailyLimit); err == nil {
			s.coolDownUntil = nullableTime(coolDown)
			s.lastRunAt = nullableTime(lastRun)
			subs = append(subs, s)
		}
	}
	rows.Close()

	submitted, skipped := 0, 0
	for _, s := range subs {
		if s.status == "cool_down" && s.coolDownUntil != nil && now.Before(*s.coolDownUntil) {
			skipped++
			continue
		}
		remaining := s.dailyLimit
		if s.lastRunAt != nil && s.lastRunAt.After(todayStart) {
			remaining = s.dailyLimit - s.lastRunCount
		}
		if remaining <= 0 {
			skipped++
			continue
		}
		inputJSON := mustJSON(map[string]any{"category_code": s.code})
		if _, _, _, err := env.Store.SubmitCoreTask("cs_feed_fetch_category", inputJSON, "", 900); err != nil {
			skipped++
			continue
		}
		submitted++
	}
	return map[string]any{
		"proposal":  map[string]any{"kind": "cs_categories_sync", "categories": catItems},
		"submitted": submitted, "skipped": skipped,
	}, nil
}

// ---------- 小工具 ----------

func intOf(v any, def int) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case json.Number:
		if i, err := n.Int64(); err == nil {
			return int(i)
		}
	}
	return def
}

func orDefault(s, def string) string {
	if s == "" {
		return def
	}
	return s
}

func nullableTime(nt sql.NullTime) *time.Time {
	if nt.Valid {
		t := nt.Time
		return &t
	}
	return nil
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// postJSON POST JSON body → raw 响应（网关/IEEE 共用）。
func postJSON(ctx context.Context, rawURL string, body any, timeout time.Duration) ([]byte, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: timeout}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, rawURL, bytes.NewReader(payload))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("http %d: %s", resp.StatusCode, truncateStr(string(raw), 300))
	}
	return raw, nil
}
