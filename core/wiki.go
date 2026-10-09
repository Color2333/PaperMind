// 主题 Wiki 生成：主题论文上下文 + 里程碑（引用图 PageRank）→ LLM 结构化
// 生成 → save_generated_content proposal。
package core

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"
)

// milestone 里程碑条目（引用图按年最佳 seminal）。
type milestone struct {
	Year         int     `json:"year"`
	Title        string  `json:"title"`
	SeminalScore float64 `json:"seminal_score"`
}

// pageRank 引用图 PageRank（Python _pagerank 移植——20 轮迭代阻尼 0.85）。
func pageRank(nodes []string, edges [][2]string) map[string]float64 {
	if len(nodes) == 0 {
		return nil
	}
	nodeSet := map[string]bool{}
	for _, n := range nodes {
		nodeSet[n] = true
	}
	outgoing := map[string][]string{}
	for _, e := range edges {
		if nodeSet[e[0]] && nodeSet[e[1]] {
			outgoing[e[0]] = append(outgoing[e[0]], e[1])
		}
	}
	n := float64(len(nodes))
	rank := map[string]float64{}
	for _, node := range nodes {
		rank[node] = 1.0 / n
	}
	const damping = 0.85
	for iter := 0; iter < 20; iter++ {
		next := map[string]float64{}
		for _, node := range nodes {
			next[node] = (1.0 - damping) / n
		}
		for _, node := range nodes {
			refs := outgoing[node]
			if len(refs) == 0 {
				continue
			}
			share := rank[node] / float64(len(refs))
			for _, dst := range refs {
				next[dst] += damping * share
			}
		}
		rank = next
	}
	return rank
}

// graphData 主题引用图（论文节点 + citations 边）。
func (e *HandlerEnv) graphData(topicID string, limit int) (nodes []string, edges [][2]string) {
	var rows *sql.Rows
	var err error
	if topicID != "" {
		rows, err = e.Store.DB.Query(
			`SELECT DISTINCT p.id FROM papers p JOIN paper_topics pt ON pt.paper_id=p.id WHERE pt.topic_id=$1 LIMIT $2`,
			topicID, limit)
	} else {
		rows, err = e.Store.DB.Query(`SELECT id FROM papers ORDER BY created_at DESC LIMIT $1`, limit)
	}
	if err != nil {
		return nil, nil
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if rows.Scan(&id) == nil {
			nodes = append(nodes, id)
		}
	}
	edgeRows, err := e.Store.DB.Query(`SELECT source_paper_id, target_paper_id FROM citations`)
	if err != nil {
		return nodes, nil
	}
	defer edgeRows.Close()
	for edgeRows.Next() {
		var s, t string
		if edgeRows.Scan(&s, &t) == nil {
			edges = append(edges, [2]string{s, t})
		}
	}
	return nodes, edges
}

// milestonesForTopic 引用图里程碑：PageRank 分最高的论文按年取最佳。
func (e *HandlerEnv) milestonesForTopic(topicID string, limit int) []milestone {
	nodes, edges := e.graphData(topicID, limit)
	if len(nodes) == 0 {
		return nil
	}
	rank := pageRank(nodes, edges)
	// 取分数 top 30 的论文标题 + 年份
	type pr struct {
		id    string
		score float64
	}
	var scored []pr
	for _, n := range nodes {
		scored = append(scored, pr{n, rank[n]})
	}
	sort.Slice(scored, func(i, j int) bool { return scored[i].score > scored[j].score })
	if len(scored) > 30 {
		scored = scored[:30]
	}
	var out []milestone
	for _, s := range scored {
		var title string
		var pubDate string
		pubExpr := `COALESCE(publication_date,'')`
		if e.Store.pg() {
			pubExpr = `COALESCE(TO_CHAR(publication_date,'YYYY-MM-DD'),'')`
		}
		err := e.Store.DB.QueryRow(
			`SELECT title, `+pubExpr+` FROM papers WHERE id=$1`, s.id,
		).Scan(&title, &pubDate)
		if err != nil || title == "" {
			continue
		}
		year := 0
		fmt.Sscanf(pubDate, "%d", &year) // "2024-05-01" → 2024
		if year == 0 {
			continue
		}
		out = append(out, milestone{Year: year, Title: title, SeminalScore: s.score})
	}
	// 每年取最高分
	best := map[int]milestone{}
	var years []int
	for _, m := range out {
		if existing, ok := best[m.Year]; !ok || m.SeminalScore > existing.SeminalScore {
			if !ok {
				years = append(years, m.Year)
			}
			best[m.Year] = m
		}
	}
	sort.Ints(years)
	var result []milestone
	for _, y := range years {
		result = append(result, best[y])
	}
	return result
}

// paperContextForWiki 主题论文上下文（标题+摘要+分析，与 Python paper_contexts 对齐）。
func (e *HandlerEnv) paperContextsForWiki(topicID, keyword string, limit int) []map[string]any {
	query := `SELECT p.title, COALESCE(p.abstract,''), COALESCE(p.publication_date,''), COALESCE(ar.summary_md,'')
	          FROM papers p
	          LEFT JOIN analysis_reports ar ON ar.paper_id = p.id`
	var args []any
	if topicID != "" {
		query += ` JOIN paper_topics pt ON pt.paper_id = p.id WHERE pt.topic_id=$1`
		args = append(args, topicID)
	} else {
		query += ` WHERE LOWER(p.title) LIKE LOWER($1) OR LOWER(p.abstract) LIKE LOWER($1)`
		args = append(args, "%"+keyword+"%")
	}
	query += fmt.Sprintf(` ORDER BY p.created_at DESC LIMIT $%d`, len(args)+1)
	args = append(args, limit)
	rows, err := e.Store.DB.Query(query, args...)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []map[string]any
	idx := 0
	for rows.Next() {
		var title, abstract, pubDate, analysis string
		if rows.Scan(&title, &abstract, &pubDate, &analysis) != nil {
			continue
		}
		year := "?"
		if len(pubDate) >= 4 {
			year = pubDate[:4]
		}
		if len(analysis) > 400 {
			analysis = analysis[:400]
		}
		if len(abstract) > 400 {
			abstract = abstract[:400]
		}
		idx++
		out = append(out, map[string]any{
			"idx": idx, "title": title, "year": year,
			"abstract": abstract, "analysis": analysis,
		})
	}
	return out
}

// TopicWikiMarkdown 生成主题 Wiki markdown（goserver 端点与 worker handler 复用）。
func (e *HandlerEnv) TopicWikiMarkdown(ctx context.Context, keyword, topicID string, limit int) (string, map[string]any, error) {
	if limit <= 0 {
		limit = 120
	}
	contexts := e.paperContextsForWiki(topicID, keyword, 25)
	ms := e.milestonesForTopic(topicID, limit)
	var ctxLines []string
	for _, p := range contexts {
		ctxLines = append(ctxLines, fmt.Sprintf("\n[P%d] %s (%v)\nAbstract: %v\nAnalysis: %v\n",
			p["idx"], p["title"], p["year"], p["abstract"], p["analysis"]))
	}
	var msLines []string
	for _, m := range ms {
		msLines = append(msLines, fmt.Sprintf("- %d: %s (seminal_score=%.3f)", m.Year, m.Title, m.SeminalScore))
	}
	prompt := "你是一位世界顶级的学术综述作者和知识百科编辑。" +
		"请基于以下真实论文数据和分析结果，撰写一篇全面、深入、结构清晰的主题百科文章。\n\n" +
		"## 输出要求\n请输出严格的 JSON 对象，结构如下：\n" +
		"{\n  \"overview\": \"主题概述（1000-2000字，涵盖定义、重要性、核心思想、发展脉络，需深入展开）\",\n" +
		"  \"sections\": [{\"title\": \"章节标题\", \"content\": \"章节内容（800-1500字，引用具体论文，用[P1][P2]标记引用来源，深度分析）\"}],\n" +
		"  \"key_findings\": [\"重要发现1（引用来源论文）\", \"重要发现2\"]\n}\n\n" +
		fmt.Sprintf("主题关键词: %s\n论文数据:\n%s\n里程碑:\n%s\n",
			keyword, strings.Join(ctxLines, ""), strings.Join(msLines, "\n"))

	parsed, res, err := e.Gateway.CompleteJSON(ctx, "deep", prompt)
	if err != nil {
		return "", nil, err
	}
	_ = res
	// 渲染 markdown
	var b strings.Builder
	if overview := stringOf(parsed["overview"]); overview != "" {
		fmt.Fprintf(&b, "# %s\n\n%s\n\n", keyword, overview)
	} else {
		fmt.Fprintf(&b, "# %s\n\n", keyword)
	}
	if sections, ok := parsed["sections"].([]any); ok {
		for _, sAny := range sections {
			s, ok := sAny.(map[string]any)
			if !ok {
				continue
			}
			fmt.Fprintf(&b, "## %s\n\n%s\n\n", stringOf(s["title"]), stringOf(s["content"]))
		}
	}
	if findings, ok := parsed["key_findings"].([]any); ok && len(findings) > 0 {
		b.WriteString("## 关键发现\n\n")
		for _, f := range findings {
			fmt.Fprintf(&b, "- %s\n", stringOf(f))
		}
	}
	metadata := map[string]any{
		"keyword": keyword, "paper_count": len(contexts),
		"milestone_count": len(ms),
	}
	return b.String(), metadata, nil
}

// HandleTopicWikiSave topic_wiki_save：Wiki 生成 + generated_contents proposal。
func HandleTopicWikiSave(ctx context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	keyword, _ := task.Input["keyword"].(string)
	limit := intOf(task.Input["limit"], 120)
	if keyword == "" {
		return nil, fmt.Errorf("缺少 keyword")
	}
	// keyword → 主题（按名精确匹配取 topic_id，供上下文聚焦）
	var topicID string
	_ = e.Store.DB.QueryRow(`SELECT id FROM topic_subscriptions WHERE name=$1`, keyword).Scan(&topicID)
	markdown, metadata, err := e.TopicWikiMarkdown(ctx, keyword, topicID, limit)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind": "save_generated_content", "content_type": "topic_wiki",
			"title": "Topic Wiki: " + keyword, "markdown": markdown,
			"keyword": keyword, "metadata_json": metadata,
		},
	}, nil
}

// PaperWikiMarkdown 论文 Wiki 生成（goserver /wiki/paper 复用）：
// 论文 + 分析 + 引用邻接 → LLM 结构化 wiki markdown。
func (e *HandlerEnv) PaperWikiMarkdown(ctx context.Context, paperID string) (string, map[string]any, error) {
	var title, abstract, arxivID, analysis string
	pubExpr := `COALESCE(publication_date,'')`
	if e.Store.pg() {
		pubExpr = `COALESCE(TO_CHAR(publication_date,'YYYY-MM-DD'),'')`
	}
	err := e.Store.DB.QueryRow(
		`SELECT title, COALESCE(abstract,''), COALESCE(arxiv_id,''), `+pubExpr+`,
		        COALESCE(ar.summary_md,'') FROM papers p
		 LEFT JOIN analysis_reports ar ON ar.paper_id = p.id WHERE p.id=$1`, paperID,
	).Scan(&title, &abstract, &arxivID, &analysis)
	if err != nil {
		return "", nil, fmt.Errorf("论文 %s 不存在", paperID)
	}
	// 引用邻接（引用/被引各取 8）
	var ancestors, descendants []string
	rows, err := e.Store.DB.Query(
		`SELECT 'ref', p2.title FROM citations c JOIN papers p2 ON p2.id = c.target_paper_id WHERE c.source_paper_id=$1
		 UNION ALL
		 SELECT 'cite', p2.title FROM citations c JOIN papers p2 ON p2.id = c.source_paper_id WHERE c.target_paper_id=$1
		 LIMIT 16`, paperID)
	if err == nil {
		for rows.Next() {
			var dir, t string
			if rows.Scan(&dir, &t) == nil {
				if dir == "ref" {
					descendants = append(descendants, t)
				} else {
					ancestors = append(ancestors, t)
				}
			}
		}
		rows.Close()
	}
	prompt := "你是学术百科编辑。请为以下论文生成结构化 Wiki，输出严格 JSON：\n" +
		`{"overview":"论文概述（300-500字，中文）","sections":[{"title":"章节","content":"内容（引用上文）"}],"key_findings":["要点"]}` + "\n\n" +
		fmt.Sprintf("标题: %s\narXiv: %s\n摘要: %s\n粗读分析: %s\n引用的上游论文: %s\n被引用于: %s\n",
			title, arxivID, truncateRunes2(abstract, 1200), truncateRunes2(analysis, 800),
			strings.Join(ancestors, "; "), strings.Join(descendants, "; "))
	parsed, _, err := e.Gateway.CompleteJSON(ctx, "deep", prompt)
	if err != nil {
		return "", nil, err
	}
	var b strings.Builder
	if overview := stringOf(parsed["overview"]); overview != "" {
		fmt.Fprintf(&b, "# %s\n\n%s\n\n", title, overview)
	}
	if sections, ok := parsed["sections"].([]any); ok {
		for _, sAny := range sections {
			s, ok := sAny.(map[string]any)
			if !ok {
				continue
			}
			fmt.Fprintf(&b, "## %s\n\n%s\n\n", stringOf(s["title"]), stringOf(s["content"]))
		}
	}
	if findings, ok := parsed["key_findings"].([]any); ok && len(findings) > 0 {
		b.WriteString("## 关键发现\n\n")
		for _, f := range findings {
			fmt.Fprintf(&b, "- %s\n", stringOf(f))
		}
	}
	metadata := map[string]any{"paper_id": paperID, "arxiv_id": arxivID}
	return b.String(), metadata, nil
}

func truncateRunes2(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n]) + "…"
}

// RecommendationItem 推荐条目（/papers/recommended 与 /today 复用）。
type RecommendationItem struct {
	ID       string   `json:"id"`
	Title    string   `json:"title"`
	ArxivID  string   `json:"arxiv_id"`
	Abstract string   `json:"abstract"`
	Score    float64  `json:"similarity"`
	TitleZh  string   `json:"title_zh,omitempty"`
	Keywords []string `json:"keywords,omitempty"`
}

// cosine 相似度（维度不齐返回 0）。
func cosine(a, b []float64) float64 {
	if len(a) == 0 || len(a) != len(b) {
		return 0
	}
	var dot, na, nb float64
	for i := range a {
		dot += a[i] * b[i]
		na += a[i] * a[i]
		nb += b[i] * b[i]
	}
	if na == 0 || nb == 0 {
		return 0
	}
	return dot / (math.Sqrt(na) * math.Sqrt(nb))
}

// Recommendations 多兴趣推荐（已读 embedding 质心 × 未读候选，主题加权 1.2）。
func (e *HandlerEnv) Recommendations(topK int) []RecommendationItem {
	if topK <= 0 {
		topK = 5
	}
	// 兴趣质心：已读论文 embedding 均值
	rows, err := e.Store.DB.Query(
		`SELECT embedding_vec FROM papers WHERE read_status IN ('skimmed','deep_read') AND embedding_vec IS NOT NULL LIMIT 200`)
	if err != nil {
		return nil
	}
	var readVecs [][]float64
	for rows.Next() {
		var raw []byte
		if rows.Scan(&raw) != nil {
			continue
		}
		var v []float64
		if json.Unmarshal(raw, &v) == nil && len(v) > 0 {
			readVecs = append(readVecs, v)
		}
	}
	rows.Close()
	if len(readVecs) == 0 {
		return nil
	}
	dim := len(readVecs[0])
	centroid := make([]float64, dim)
	n := 0
	for _, v := range readVecs {
		if len(v) != dim {
			continue
		}
		for i := range v {
			centroid[i] += v[i]
		}
		n++
	}
	if n == 0 {
		return nil
	}
	for i := range centroid {
		centroid[i] /= float64(n)
	}
	// 订阅主题论文加权集
	topicPapers := map[string]bool{}
	trows, err := e.Store.DB.Query(
		`SELECT pt.paper_id FROM paper_topics pt JOIN topic_subscriptions t ON t.id=pt.topic_id WHERE t.enabled = true`)
	if err == nil {
		for trows.Next() {
			var pid string
			if trows.Scan(&pid) == nil {
				topicPapers[pid] = true
			}
		}
		trows.Close()
	}
	// 未读候选
	crows, err := e.Store.DB.Query(
		`SELECT p.id, p.title, COALESCE(p.arxiv_id,''), COALESCE(p.abstract,''), COALESCE(p.metadata,'{}'),
		        p.embedding_vec, rejected FROM papers p
		 WHERE p.read_status='unread' AND p.embedding_vec IS NOT NULL AND p.rejected = false
		 ORDER BY p.created_at DESC LIMIT 500`)
	if err != nil {
		return nil
	}
	defer crows.Close()
	type scored struct {
		item  RecommendationItem
		score float64
	}
	var candidates []scored
	for crows.Next() {
		var id, title, arxivID, abstract, metaRaw string
		var embRaw []byte
		var rejected bool
		if err := crows.Scan(&id, &title, &arxivID, &abstract, &metaRaw, &embRaw, &rejected); err != nil {
			continue
		}
		var vec []float64
		if json.Unmarshal(embRaw, &vec) != nil {
			continue
		}
		sim := cosine(vec, centroid)
		if topicPapers[id] {
			sim *= 1.2
		}
		item := RecommendationItem{
			ID: id, Title: title, ArxivID: arxivID,
			Abstract: truncateRunes2(abstract, 300), Score: sim,
		}
		var meta map[string]any
		if json.Unmarshal([]byte(metaRaw), &meta) == nil {
			item.TitleZh = stringOf(meta["title_zh"])
			if kws, ok := meta["keywords"].([]any); ok {
				for _, k := range kws {
					item.Keywords = append(item.Keywords, stringOf(k))
				}
			}
		}
		candidates = append(candidates, scored{item, sim})
	}
	sort.Slice(candidates, func(i, j int) bool { return candidates[i].score > candidates[j].score })
	out := make([]RecommendationItem, 0, topK)
	for _, c := range candidates {
		if len(out) >= topK {
			break
		}
		out = append(out, c.item)
	}
	return out
}
