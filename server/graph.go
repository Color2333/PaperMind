// Phase 6（下）：graph 20 端点 —— networkx→Go 原生实现
// （PageRank 迭代、BFS 引用树、PCA 降维、k-means、共引配对、桥接检测）。
package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"math"
	"math/rand"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	core "github.com/Color2333/PaperMind/core"
)

// llmCache LLM 洞察端点的进程内 TTL 缓存（Python 语义对齐：survey/evolution
// 300s、gaps 600s——重生成成本高，短缓存避免每次点击重跑 2 次 LLM）。
var (
	llmCacheMu sync.Mutex
	llmCache   = map[string]llmCacheEntry{}
)

type llmCacheEntry struct {
	data     map[string]any
	expires  time.Time
}

func llmCacheGet(key string) (map[string]any, bool) {
	llmCacheMu.Lock()
	defer llmCacheMu.Unlock()
	e, ok := llmCache[key]
	if !ok || time.Now().After(e.expires) {
		return nil, false
	}
	return e.data, true
}

func llmCacheSet(key string, data map[string]any, ttl time.Duration) {
	llmCacheMu.Lock()
	defer llmCacheMu.Unlock()
	// 简单防膨胀：超 256 条清空过期项
	if len(llmCache) > 256 {
		now := time.Now()
		for k, v := range llmCache {
			if now.After(v.expires) {
				delete(llmCache, k)
			}
		}
	}
	llmCache[key] = llmCacheEntry{data: data, expires: time.Now().Add(ttl)}
}

// graphEdge 引用边。
type graphEdge struct{ Source, Target string }

// loadGraphEdges 全部引用边（papers 限定的过滤由调用方做）。
func (s *Server) loadGraphEdges() []graphEdge {
	rows, err := s.db.Query(`SELECT source_paper_id, target_paper_id FROM citations`)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []graphEdge
	for rows.Next() {
		var e graphEdge
		if rows.Scan(&e.Source, &e.Target) == nil {
			out = append(out, e)
		}
	}
	return out
}

// graphPaper 图节点基础字段。
type graphPaper struct {
	ID, Title, ArxivID string
	Year               *int
	ReadStatus         string
}

func (s *Server) loadGraphPapers(limit int) []graphPaper {
	pubExpr := `NULL`
	if true { // PG 方言（生产）
		pubExpr = `TO_CHAR(publication_date,'YYYY')`
	}
	rows, err := s.db.Query(
		`SELECT id, COALESCE(title,''), COALESCE(arxiv_id,''), ` + pubExpr + `, COALESCE(read_status,'unread')
		 FROM papers ORDER BY created_at DESC LIMIT $1`, limit)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []graphPaper
	for rows.Next() {
		var p graphPaper
		var year sql.NullString
		if rows.Scan(&p.ID, &p.Title, &p.ArxivID, &year, &p.ReadStatus) == nil {
			if year.Valid && year.String != "" {
				y := 0
				fmt.Sscanf(year.String, "%d", &y)
				if y > 0 {
					p.Year = &y
				}
			}
			out = append(out, p)
		}
	}
	return out
}

// ---------- overview / timeline / quality ----------

// handleGraphOverview GET /graph/overview。
func (s *Server) handleGraphOverview(w http.ResponseWriter, r *http.Request) {
	papers := s.loadGraphPapers(50000)
	edges := s.loadGraphEdges()
	idSet := map[string]bool{}
	for _, p := range papers {
		idSet[p.ID] = true
	}
	valid := []graphEdge{}
	for _, e := range edges {
		if idSet[e.Source] && idSet[e.Target] {
			valid = append(valid, e)
		}
	}
	inDeg, outDeg := map[string]int{}, map[string]int{}
	ids := make([]string, len(papers))
	for i, p := range papers {
		ids[i] = p.ID
	}
	for _, e := range valid {
		outDeg[e.Source]++
		inDeg[e.Target]++
	}
	pr := core.PageRank(ids, edgePairs(valid))
	// paper→topics
	topicOf := map[string][]string{}
	trows, err := s.db.Query(
		`SELECT pt.paper_id, COALESCE(t.name,'未分配') FROM paper_topics pt
		 LEFT JOIN topic_subscriptions t ON t.id = pt.topic_id`)
	if err == nil {
		for trows.Next() {
			var pid, tn string
			if trows.Scan(&pid, &tn) == nil {
				topicOf[pid] = append(topicOf[pid], tn)
			}
		}
		trows.Close()
	}
	nodes := make([]map[string]any, 0, len(papers))
	for _, p := range papers {
		nodes = append(nodes, map[string]any{
			"id": p.ID, "title": p.Title, "arxiv_id": p.ArxivID, "year": p.Year,
			"in_degree": inDeg[p.ID], "out_degree": outDeg[p.ID],
			"pagerank":  math.Round(pr[p.ID]*1e6) / 1e6,
			"topics":    orSlice(topicOf[p.ID]), "read_status": p.ReadStatus,
		})
	}
	sort.Slice(nodes, func(i, j int) bool {
		return nodes[i]["pagerank"].(float64) > nodes[j]["pagerank"].(float64)
	})
	top := nodes
	if len(top) > 10 {
		top = top[:10]
	}
	edgeList := make([]map[string]any, len(valid))
	for i, e := range valid {
		edgeList[i] = map[string]any{"source": e.Source, "target": e.Target}
	}
	topicStats := map[string]map[string]int{}
	for _, n := range nodes {
		for _, t := range n["topics"].([]string) {
			if topicStats[t] == nil {
				topicStats[t] = map[string]int{"count": 0, "edges": 0}
			}
			topicStats[t]["count"]++
		}
	}
	n := len(nodes)
	maxE := 1
	if n > 1 {
		maxE = n * (n - 1)
	}
	density := 0.0
	if maxE > 0 {
		density = math.Round(float64(len(edgeList))/float64(maxE)*1e6) / 1e6
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"total_papers": n, "total_edges": len(edgeList), "density": density,
		"nodes": nodes, "edges": edgeList, "top_papers": top, "topic_stats": topicStats,
	})
}

func edgePairs(edges []graphEdge) [][2]string {
	out := make([][2]string, len(edges))
	for i, e := range edges {
		out[i] = [2]string{e.Source, e.Target}
	}
	return out
}

// handleGraphTimeline GET /graph/timeline?keyword=&limit= —— PageRank 里程碑。
// 契约：TimelineResponse{keyword, timeline[], seminal[], milestones[]}。
func (s *Server) handleGraphTimeline(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	limit := queryInt(r, "limit", 100)
	papers := s.loadGraphPapers(2000)
	edges := s.loadGraphEdges()
	idSet := map[string]bool{}
	for _, p := range papers {
		idSet[p.ID] = true
	}
	valid := []graphEdge{}
	for _, e := range edges {
		if idSet[e.Source] && idSet[e.Target] {
			valid = append(valid, e)
		}
	}
	pr := core.PageRank(keys(idSet), edgePairs(valid))
	inDeg, outDeg := map[string]int{}, map[string]int{}
	for _, e := range valid {
		inDeg[e.Target]++
		outDeg[e.Source]++
	}
	// 关键词匹配：标题/分类/主题名（洞察面板传主题名）
	var kwIDs map[string]bool
	if kw := strings.TrimSpace(keyword); kw != "" {
		kwIDs = map[string]bool{}
		for _, id := range s.paperIDsForKeyword(kw, 2000) {
			kwIDs[id] = true
		}
	}
	type item struct {
		paper         graphPaper
		score         float64
		inDeg, outDeg int
	}
	var items []item
	for _, p := range papers {
		if kwIDs != nil && !kwIDs[p.ID] {
			continue
		}
		items = append(items, item{p, pr[p.ID], inDeg[p.ID], outDeg[p.ID]})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].score > items[j].score })
	toEntry := func(it item) map[string]any {
		year := 0
		if it.paper.Year != nil {
			year = *it.paper.Year
		}
		return map[string]any{
			"paper_id": it.paper.ID, "title": it.paper.Title, "year": year,
			"indegree": it.inDeg, "outdegree": it.outDeg,
			"pagerank":      math.Round(it.score*1e4) / 1e4,
			"seminal_score": math.Round(it.score*1e3) / 1e3,
			"why_seminal":   fmt.Sprintf("indegree=%d, pagerank=%.4f", it.inDeg, it.score),
		}
	}
	timeline := []map[string]any{}
	n := len(items)
	if n > limit {
		n = limit
	}
	for i := 0; i < n; i++ {
		timeline = append(timeline, toEntry(items[i]))
	}
	seminal := timeline
	if len(seminal) > 20 {
		seminal = seminal[:20]
	}
	best := map[int]map[string]any{}
	var years []int
	for _, e := range timeline {
		y, _ := e["year"].(int)
		if y == 0 {
			continue
		}
		if _, ok := best[y]; !ok {
			years = append(years, y)
			best[y] = e
		}
	}
	sort.Ints(years)
	milestones := []map[string]any{}
	for _, y := range years {
		milestones = append(milestones, best[y])
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"keyword": keyword, "timeline": timeline,
		"seminal": seminal, "milestones": milestones,
	})
}

// handleGraphQuality GET /graph/quality?keyword=&limit=。
// 契约：GraphQuality{keyword, node_count, edge_count, density, connected_node_ratio, publication_date_coverage}。
func (s *Server) handleGraphQuality(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	limit := queryInt(r, "limit", 120)
	var papers []graphPaper
	if kw := strings.TrimSpace(keyword); kw != "" {
		// 按关键词命中的论文统计（标题/分类/主题）
		ids := s.paperIDsForKeyword(kw, limit)
		idSet := map[string]bool{}
		for _, id := range ids {
			idSet[id] = true
		}
		for _, p := range s.loadGraphPapers(limit * 3) {
			if idSet[p.ID] {
				papers = append(papers, p)
			}
		}
	} else {
		papers = s.loadGraphPapers(limit)
	}
	edges := s.loadGraphEdges()
	idSet := map[string]bool{}
	for _, p := range papers {
		idSet[p.ID] = true
	}
	var internal []graphEdge
	connected := map[string]bool{}
	for _, e := range edges {
		if idSet[e.Source] && idSet[e.Target] {
			internal = append(internal, e)
			connected[e.Source], connected[e.Target] = true, true
		}
	}
	withPub := 0
	for _, p := range papers {
		if p.Year != nil {
			withPub++
		}
	}
	n := len(papers)
	ie := len(internal)
	density := 0.0
	if n > 1 {
		density = math.Round(float64(ie)/float64(n*(n-1))*1e6) / 1e6
	}
	connRatio := 0.0
	if n > 0 {
		connRatio = math.Round(float64(len(connected))/float64(n)*1e4) / 1e4
	}
	pubCoverage := 0.0
	if n > 0 {
		pubCoverage = math.Round(float64(withPub)/float64(n)*1e4) / 1e4
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"keyword":                   keyword,
		"node_count":                n,
		"edge_count":                ie,
		"density":                   density,
		"connected_node_ratio":      connRatio,
		"publication_date_coverage": pubCoverage,
	})
}

// ---------- 引用树 / 网络 ----------

// bfsEdges BFS 展开引用方向（Python citation_tree bfs 对齐）。
func bfsEdges(start string, graph map[string][]string, depth int) []map[string]any {
	visited := map[string]bool{start: true}
	type qItem struct {
		node string
		d    int
	}
	queue := []qItem{{start, 0}}
	var result []map[string]any
	for len(queue) > 0 {
		cur := queue[0]
		queue = queue[1:]
		if cur.d >= depth {
			continue
		}
		for _, nxt := range graph[cur.node] {
			result = append(result, map[string]any{"source": cur.node, "target": nxt, "depth": cur.d + 1})
			if !visited[nxt] {
				visited[nxt] = true
				queue = append(queue, qItem{nxt, cur.d + 1})
			}
		}
	}
	return result
}

// handleCitationTree GET /graph/citation-tree/{paper_id}。
// 契约：CitationTree{root, root_title, ancestors:[CitationEdge], descendants:[CitationEdge], nodes:[CitationNode], edge_count}。
func (s *Server) handleCitationTree(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	depth := queryInt(r, "depth", 2)
	outEdges, inEdges := map[string][]string{}, map[string][]string{}
	for _, e := range s.loadGraphEdges() {
		outEdges[e.Source] = append(outEdges[e.Source], e.Target)
		inEdges[e.Target] = append(inEdges[e.Target], e.Source)
	}
	ancestors := bfsEdges(paperID, outEdges, depth)
	descendants := bfsEdges(paperID, inEdges, depth)
	nodeInfo := map[string]map[string]any{}
	fetch := func(pid string) {
		if _, ok := nodeInfo[pid]; ok {
			return
		}
		var title string
		var year sql.NullString
		if err := s.db.QueryRow(
			`SELECT COALESCE(title,''), TO_CHAR(publication_date,'YYYY') FROM papers WHERE id=$1`, pid,
		).Scan(&title, &year); err == nil && title != "" {
			var yr any
			if year.Valid && year.String != "" {
				if y, e := strconv.Atoi(year.String); e == nil {
					yr = y
				}
			}
			nodeInfo[pid] = map[string]any{"id": pid, "title": title, "year": yr}
		}
	}
	fetch(paperID)
	for _, e := range append(ancestors, descendants...) {
		fetch(strOf(e["source"]))
		fetch(strOf(e["target"]))
	}
	nodes := make([]map[string]any, 0, len(nodeInfo))
	for _, info := range nodeInfo {
		nodes = append(nodes, info)
	}
	var rootTitle string
	_ = s.db.QueryRow(`SELECT COALESCE(title,'') FROM papers WHERE id=$1`, paperID).Scan(&rootTitle)
	writeJSON(w, http.StatusOK, map[string]any{
		"root":         paperID,
		"root_title":   rootTitle,
		"ancestors":    ancestors,
		"descendants":  descendants,
		"nodes":        nodes,
		"edge_count":   len(ancestors) + len(descendants),
	})
}

func strOrNull(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// handleTopicCitationNetwork GET /graph/citation-network/topic/{topic_id}。
// 契约：TopicCitationNetwork{topic_id, topic_name, nodes:[NetworkNode], edges, stats{...}}。
func (s *Server) handleTopicCitationNetwork(w http.ResponseWriter, r *http.Request) {
	topicID := r.PathValue("topic_id")
	rows, err := s.db.Query(
		`SELECT p.id, COALESCE(p.title,''), COALESCE(p.arxiv_id,''),
		        COALESCE(TO_CHAR(p.publication_date,'YYYY'),'')
		 FROM papers p JOIN paper_topics pt ON pt.paper_id = p.id
		 WHERE pt.topic_id=$1 LIMIT 500`, topicID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	type node struct {
		id, title, arxiv, year string
		inDeg, outDeg          int
	}
	members := map[string]*node{}
	var order []string
	for rows.Next() {
		n := &node{}
		if rows.Scan(&n.id, &n.title, &n.arxiv, &n.year) == nil {
			members[n.id] = n
			order = append(order, n.id)
		}
	}
	rows.Close()
	edges := []map[string]any{}
	for _, e := range s.loadGraphEdges() {
		if _, okS := members[e.Source]; okS {
			if _, okT := members[e.Target]; okT {
				edges = append(edges, map[string]any{"source": e.Source, "target": e.Target})
				members[e.Target].inDeg++
				members[e.Source].outDeg++
			}
		}
	}
	var topicName string
	_ = s.db.QueryRow(`SELECT COALESCE(name,'') FROM topic_subscriptions WHERE id=$1`, topicID).Scan(&topicName)
	nodes := make([]map[string]any, 0, len(order))
	hubPapers := 0
	maxIn := 0
	for _, n := range members {
		if n.inDeg > maxIn {
			maxIn = n.inDeg
		}
	}
	for _, id := range order {
		n := members[id]
		y := 0
		fmt.Sscanf(n.year, "%d", &y)
		isHub := n.inDeg >= 3 && (maxIn == 0 || n.inDeg >= maxIn/2)
		if isHub {
			hubPapers++
		}
		var yr any
		if y > 0 {
			yr = y
		}
		nodes = append(nodes, map[string]any{
			"id": n.id, "title": n.title, "year": yr,
			"arxiv_id": strOrNull(n.arxiv), "in_degree": n.inDeg, "out_degree": n.outDeg,
			"is_hub": isHub, "is_external": false,
		})
	}
	totalPapers := len(nodes)
	totalEdges := len(edges)
	density := 0.0
	if totalPapers > 1 {
		density = math.Round(float64(totalEdges)/float64(totalPapers*(totalPapers-1))*1e6) / 1e6
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"topic_id": topicID, "topic_name": topicName,
		"nodes": nodes, "edges": edges,
		"stats": map[string]any{
			"total_papers": totalPapers, "total_edges": totalEdges,
			"density": density, "hub_papers": hubPapers,
			"internal_papers": totalPapers, "external_papers": 0,
			"internal_edges": totalEdges,
		},
	})
}

// handleTopicDeepTrace POST /graph/citation-network/topic/{topic_id}/deep-trace
// —— 提交引用同步任务链（外部 API 副作用走 durable task）。
func (s *Server) handleTopicDeepTrace(w http.ResponseWriter, r *http.Request) {
	topicID := r.PathValue("topic_id")
	jobID, taskID, err := s.submitCoreTask("sync_citations_topic", map[string]any{
		"topic_id": topicID, "paper_limit": 30, "edge_limit_per_paper": 6,
	}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// richEntry RichCitationEntry 形状（库内条目 scholar 字段为 null，in_library=true）。
func (s *Server) richEntry(paperID, title, arxiv, ctx string) map[string]any {
	var contextAny any
	if ctx != "" {
		contextAny = ctx
	}
	return map[string]any{
		"scholar_id": nil, "title": title, "year": nil, "venue": nil,
		"citation_count": nil, "arxiv_id": strOrNull(arxiv), "abstract": nil,
		"in_library": true, "library_paper_id": paperID,
		"context": contextAny,
	}
}

// handleCitationDetail GET /graph/citation-detail/{paper_id} —— 库内引用详情。
func (s *Server) handleCitationDetail(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	references := []map[string]any{}
	rows, err := s.db.Query(
		`SELECT p.id, COALESCE(p.title,''), COALESCE(p.arxiv_id,''), c.context
		 FROM citations c JOIN papers p ON p.id = c.target_paper_id
		 WHERE c.source_paper_id=$1 ORDER BY c.created_at DESC`, paperID)
	if err == nil {
		for rows.Next() {
			var id, title, arxiv string
			var ctx sql.NullString
			if rows.Scan(&id, &title, &arxiv, &ctx) == nil {
				references = append(references, s.richEntry(id, title, arxiv, ctx.String))
			}
		}
		rows.Close()
	}
	citations := []map[string]any{}
	rows, err = s.db.Query(
		`SELECT p.id, COALESCE(p.title,''), COALESCE(p.arxiv_id,''), c.context
		 FROM citations c JOIN papers p ON p.id = c.source_paper_id
		 WHERE c.target_paper_id=$1 ORDER BY c.created_at DESC`, paperID)
	if err == nil {
		for rows.Next() {
			var id, title, arxiv string
			var ctx sql.NullString
			if rows.Scan(&id, &title, &arxiv, &ctx) == nil {
				citations = append(citations, s.richEntry(id, title, arxiv, ctx.String))
			}
		}
		rows.Close()
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"paper_id": paperID, "references": references, "cited_by": citations,
		"stats": map[string]any{
			"total_references":        len(references),
			"total_cited_by":          len(citations),
			"in_library_references":   len(references),
			"in_library_cited_by":     len(citations),
		},
	})
}

// ---------- 桥接 / 前沿 / 共引 ----------

// handleGraphBridges GET /graph/bridges —— 跨主题桥接论文。
// 契约：BridgesResponse{bridges:[{id,title,arxiv_id,topics_citing,cross_topic_count,own_topics}], total}。
// 语义：被「其他主题」的论文引用的桥接节点（跨主题入边视角）。
func (s *Server) handleGraphBridges(w http.ResponseWriter, r *http.Request) {
	// paper → topics
	paperTopics := map[string][]string{}
	rows, err := s.db.Query(
		`SELECT pt.paper_id, COALESCE(t.name,'未分配') FROM paper_topics pt
		 LEFT JOIN topic_subscriptions t ON t.id = pt.topic_id`)
	if err == nil {
		for rows.Next() {
			var pid, tn string
			if rows.Scan(&pid, &tn) == nil {
				paperTopics[pid] = append(paperTopics[pid], tn)
			}
		}
		rows.Close()
	}
	// source_paper_id → {title, arxiv_id}
	paperMeta := map[string][2]string{}
	metaRows, err := s.db.Query(`SELECT id, COALESCE(title,''), COALESCE(arxiv_id,'') FROM papers`)
	if err == nil {
		for metaRows.Next() {
			var id, title, arxiv string
			if metaRows.Scan(&id, &title, &arxiv) == nil {
				paperMeta[id] = [2]string{title, arxiv}
			}
		}
		metaRows.Close()
	}
	type bridge struct {
		id, title, arxiv string
		citingTopics     map[string]bool
		ownTopics        []string
		crossCount       int
	}
	bridges := map[string]*bridge{}
	for _, e := range s.loadGraphEdges() {
		dstTopics := paperTopics[e.Target]
		srcTopics := paperTopics[e.Source]
		if len(dstTopics) == 0 || len(srcTopics) == 0 {
			continue
		}
		// source 的主题与 target 的主题无交集 → target 是被外域引用的桥
		cross := true
		for _, st := range srcTopics {
			for _, dt := range dstTopics {
				if st == dt {
					cross = false
				}
			}
		}
		if !cross {
			continue
		}
		b := bridges[e.Target]
		if b == nil {
			meta := paperMeta[e.Target]
			b = &bridge{id: e.Target, title: meta[0], arxiv: meta[1],
				citingTopics: map[string]bool{}, ownTopics: dstTopics}
			bridges[e.Target] = b
		}
		for _, st := range srcTopics {
			if !containsStr(dstTopics, st) {
				b.citingTopics[st] = true
			}
		}
		b.crossCount++
	}
	items := make([]bridge, 0, len(bridges))
	for _, b := range bridges {
		items = append(items, *b)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].crossCount > items[j].crossCount })
	if len(items) > 20 {
		items = items[:20]
	}
	out := make([]map[string]any, len(items))
	for i, b := range items {
		topicsCiting := []string{}
		for t := range b.citingTopics {
			topicsCiting = append(topicsCiting, t)
		}
		sort.Strings(topicsCiting)
		out[i] = map[string]any{
			"id": b.id, "title": b.title, "arxiv_id": b.arxiv,
			"topics_citing":     topicsCiting,
			"cross_topic_count": len(b.citingTopics),
			"own_topics":        orSlice(b.ownTopics),
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"bridges": out, "total": len(out)})
}

func containsStr(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

// handleGraphFrontier GET /graph/frontier?days= —— 研究前沿（近期高被引新论文）。
// 契约：FrontierResponse{period_days, total_recent, frontier:[...]}。
func (s *Server) handleGraphFrontier(w http.ResponseWriter, r *http.Request) {
	days := queryInt(r, "days", 90)
	cutoff := time.Now().UTC().AddDate(0, 0, -days).Format("2006-01-02 15:04:05.000000")
	rows, err := s.db.Query(
		`SELECT p.id, COALESCE(p.title,''), COALESCE(p.arxiv_id,''),
		        COALESCE(TO_CHAR(p.publication_date,'YYYY'),''), COALESCE(TO_CHAR(p.publication_date,'YYYY-MM-DD'),''),
		        p.read_status, COUNT(c.id) AS cites
		 FROM papers p LEFT JOIN citations c ON c.target_paper_id = p.id
		 WHERE p.created_at >= $1
		 GROUP BY p.id, p.title, p.arxiv_id, p.publication_date, p.read_status
		 ORDER BY cites DESC LIMIT 20`, cutoff)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var totalRecent int
	_ = s.db.QueryRow(`SELECT COUNT(*) FROM papers WHERE created_at >= $1`, cutoff).Scan(&totalRecent)
	frontier := []map[string]any{}
	for rows.Next() {
		var id, title, arxiv, year, pubDate, readStatus string
		var cites int
		if rows.Scan(&id, &title, &arxiv, &year, &pubDate, &readStatus, &cites) == nil {
			y := 0
			fmt.Sscanf(year, "%d", &y)
			velocity := float64(cites) / float64(days) * 7 // 每周引用速度
			frontier = append(frontier, map[string]any{
				"id": id, "title": title, "arxiv_id": arxiv,
				"year": y, "publication_date": pubDate,
				"citations_in_library": cites,
				"citation_velocity":    math.Round(velocity*100) / 100,
				"read_status":          readStatus,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"period_days": days, "total_recent": totalRecent, "frontier": frontier,
	})
}

// handleCocitationClusters GET /graph/cocitation-clusters —— 共引配对聚类。
// 契约：CocitationResponse{total_clusters, clusters:[{size, papers:[{id,title,arxiv_id}]}], cocitation_pairs}。
func (s *Server) handleCocitationClusters(w http.ResponseWriter, r *http.Request) {
	minCocite := queryInt(r, "min_cocite", 2)
	targetSources := map[string]map[string]bool{}
	for _, e := range s.loadGraphEdges() {
		if targetSources[e.Target] == nil {
			targetSources[e.Target] = map[string]bool{}
		}
		targetSources[e.Target][e.Source] = true
	}
	targets := make([]string, 0, len(targetSources))
	for t := range targetSources {
		targets = append(targets, t)
	}
	sort.Strings(targets)
	type pair struct {
		a, b string
		n    int
	}
	var pairs []pair
	pairCount := 0
	for i := 0; i < len(targets); i++ {
		for j := i + 1; j < len(targets); j++ {
			shared := 0
			for src := range targetSources[targets[i]] {
				if targetSources[targets[j]][src] {
					shared++
				}
			}
			if shared > 0 {
				pairCount++
			}
			if shared >= minCocite {
				pairs = append(pairs, pair{targets[i], targets[j], shared})
			}
		}
	}
	parent := map[string]string{}
	var find func(string) string
	find = func(x string) string {
		if parent[x] == "" {
			parent[x] = x
		}
		if parent[x] != x {
			parent[x] = find(parent[x])
		}
		return parent[x]
	}
	union := func(a, b string) { parent[find(a)] = find(b) }
	for _, p := range pairs {
		union(p.a, p.b)
	}
	clusters := map[string][]string{}
	for t := range parent {
		root := find(t)
		clusters[root] = append(clusters[root], t)
	}
	out := []map[string]any{}
	for _, members := range clusters {
		if len(members) < 2 {
			continue
		}
		papers := make([]map[string]any, len(members))
		for i, m := range members {
			var title, arxiv string
			_ = s.db.QueryRow(`SELECT COALESCE(title,''), COALESCE(arxiv_id,'') FROM papers WHERE id=$1`, m).Scan(&title, &arxiv)
			papers[i] = map[string]any{"id": m, "title": title, "arxiv_id": arxiv}
		}
		out = append(out, map[string]any{"size": len(members), "papers": papers})
	}
	sort.Slice(out, func(i, j int) bool { return out[i]["size"].(int) > out[j]["size"].(int) })
	writeJSON(w, http.StatusOK, map[string]any{
		"total_clusters":   len(out),
		"clusters":         out,
		"cocitation_pairs": pairCount,
	})
}

func toAny(v any) any { return v }

// ---------- 相似度地图 / 聚类地图（PCA / k-means） ----------

// loadVectors 加载论文 embedding（limit 篇，含 topic 标签）。
func (s *Server) loadVectors(limit int, topicID string) ([]string, [][]float64, map[string][]string) {
	query := `SELECT p.id, p.embedding_vec FROM papers p`
	if topicID != "" {
		query += ` JOIN paper_topics pt ON pt.paper_id = p.id AND pt.topic_id=$2`
	}
	query += fmt.Sprintf(` WHERE p.embedding_vec IS NOT NULL ORDER BY p.created_at DESC LIMIT $%d`, map[bool]int{true: 1, false: 2}[topicID != ""])
	args := []any{}
	if topicID != "" {
		args = append(args, 50000, topicID)
	} else {
		args = append(args, limit)
	}
	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, nil, nil
	}
	defer rows.Close()
	var ids []string
	var vecs [][]float64
	for rows.Next() {
		var id string
		var raw []byte
		if rows.Scan(&id, &raw) != nil {
			continue
		}
		var v []float64
		if json.Unmarshal(raw, &v) != nil || len(v) == 0 {
			continue
		}
		ids = append(ids, id)
		vecs = append(vecs, v)
	}
	// 主题标签
	topicOf := map[string][]string{}
	trows, err := s.db.Query(
		`SELECT pt.paper_id, COALESCE(t.name,'') FROM paper_topics pt LEFT JOIN topic_subscriptions t ON t.id=pt.topic_id`)
	if err == nil {
		for trows.Next() {
			var pid, tn string
			if trows.Scan(&pid, &tn) == nil {
				topicOf[pid] = append(topicOf[pid], tn)
			}
		}
		trows.Close()
	}
	return ids, vecs, topicOf
}

// pca2 简易 PCA 降到 2 维（协方差幂迭代 top-2 特征向量）。
func pca2(vecs [][]float64) [][2]float64 {
	n := len(vecs)
	if n == 0 {
		return nil
	}
	dim := len(vecs[0])
	// 中心化
	mean := make([]float64, dim)
	for _, v := range vecs {
		for i := range v {
			mean[i] += v[i]
		}
	}
	for i := range mean {
		mean[i] /= float64(n)
	}
	centered := make([][]float64, n)
	for i, v := range vecs {
		c := make([]float64, dim)
		for j := range v {
			c[j] = v[j] - mean[j]
		}
		centered[i] = c
	}
	// 幂迭代求 top2 特征向量（正交化）
	powerIter := func(seed []float64, ortho []float64) []float64 {
		v := make([]float64, dim)
		copy(v, seed)
		for iter := 0; iter < 30; iter++ {
			next := make([]float64, dim)
			for _, row := range centered {
				dot := 0.0
				for j := range row {
					dot += row[j] * v[j]
				}
				for j := range row {
					next[j] += dot * row[j]
				}
			}
			// 正交化（对第二分量）
			if ortho != nil {
				dot := 0.0
				for j := range next {
					dot += next[j] * ortho[j]
				}
				for j := range next {
					next[j] -= dot * ortho[j]
				}
			}
			norm := 0.0
			for j := range next {
				norm += next[j] * next[j]
			}
			if norm < 1e-12 {
				return v
			}
			inv := 1.0 / math.Sqrt(norm)
			for j := range next {
				next[j] *= inv
			}
			v = next
		}
		return v
	}
	rng := rand.New(rand.NewSource(42))
	seed1 := make([]float64, dim)
	for j := range seed1 {
		seed1[j] = rng.Float64()
	}
	pc1 := powerIter(seed1, nil)
	seed2 := make([]float64, dim)
	for j := range seed2 {
		seed2[j] = rng.Float64()
	}
	pc2 := powerIter(seed2, pc1)
	out := make([][2]float64, n)
	for i, row := range centered {
		x, y := 0.0, 0.0
		for j := range row {
			x += row[j] * pc1[j]
			y += row[j] * pc2[j]
		}
		out[i] = [2]float64{math.Round(x*1e4) / 1e4, math.Round(y*1e4) / 1e4}
	}
	return out
}

// handleSimilarityMap GET /graph/similarity-map —— PCA 2D 散点。
// 契约：SimilarityMapPoint{id,title,x,y,year,read_status,topics,topic,arxiv_id}。
func (s *Server) handleSimilarityMap(w http.ResponseWriter, r *http.Request) {
	topicID := r.URL.Query().Get("topic_id")
	limit := queryInt(r, "limit", 200)
	if limit < 5 {
		limit = 5
	}
	ids, vecs, topicOf := s.loadVectors(limit, topicID)
	if len(vecs) < 5 {
		writeJSON(w, http.StatusOK, map[string]any{"points": []any{}, "message": "论文数量不足（至少需要 5 篇有向量的论文）"})
		return
	}
	proj := pca2(vecs)
	points := make([]map[string]any, len(ids))
	for i, id := range ids {
		var title, arxiv, readStatus string
		var year sql.NullString
		_ = s.db.QueryRow(
			`SELECT COALESCE(title,''), COALESCE(arxiv_id,''), COALESCE(read_status,'unread'), TO_CHAR(publication_date,'YYYY')
			 FROM papers WHERE id=$1`, id).Scan(&title, &arxiv, &readStatus, &year)
		var yr any
		if year.Valid && year.String != "" {
			if y, e := strconv.Atoi(year.String); e == nil {
				yr = y
			}
		}
		topic := ""
		if len(topicOf[id]) > 0 {
			topic = topicOf[id][0]
		}
		points[i] = map[string]any{
			"id": id, "title": title, "x": proj[i][0], "y": proj[i][1],
			"year": yr, "read_status": readStatus,
			"topics": orSlice(topicOf[id]), "topic": topic,
			"arxiv_id": arxiv,
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"points": points, "total": len(points), "method": "pca"})
}

func kmeans(vecs [][]float64, k, maxIter int) []int {
	n := len(vecs)
	if n == 0 || k < 1 {
		return nil
	}
	if k > n {
		k = n
	}
	dim := len(vecs[0])
	rng := rand.New(rand.NewSource(42))
	// 初始质心：k 个不重复点
	perm := rng.Perm(n)
	centroids := make([][]float64, k)
	for i := 0; i < k; i++ {
		centroids[i] = append([]float64{}, vecs[perm[i]]...)
	}
	assign := make([]int, n)
	for iter := 0; iter < maxIter; iter++ {
		changed := false
		for i, v := range vecs {
			best, bestSim := 0, -2.0
			for ci, c := range centroids {
				sim := cosineSim(v, c)
				if sim > bestSim {
					bestSim, best = sim, ci
				}
			}
			if assign[i] != best {
				assign[i] = best
				changed = true
			}
		}
		// 更新质心
		sums := make([][]float64, k)
		counts := make([]int, k)
		for i, v := range vecs {
			if sums[assign[i]] == nil {
				sums[assign[i]] = make([]float64, dim)
			}
			for j := range v {
				sums[assign[i]][j] += v[j]
			}
			counts[assign[i]]++
		}
		for ci := 0; ci < k; ci++ {
			if counts[ci] > 0 {
				for j := range centroids[ci] {
					centroids[ci][j] = sums[ci][j] / float64(counts[ci])
				}
			}
		}
		if !changed {
			break
		}
	}
	return assign
}

func cosineSim(a, b []float64) float64 {
	if len(a) != len(b) {
		return -2
	}
	var dot, na, nb float64
	for i := range a {
		dot += a[i] * b[i]
		na += a[i] * a[i]
		nb += b[i] * b[i]
	}
	if na == 0 || nb == 0 {
		return -2
	}
	return dot / (math.Sqrt(na) * math.Sqrt(nb))
}

// handleClusterMap GET /graph/cluster-map —— 全库 k-means 研究领域地图。
// 契约：ClusterMapData{clusters:[ClusterGroup{cluster_id, name, keywords[], size, papers}], total_clusters, total_papers}。
func (s *Server) handleClusterMap(w http.ResponseWriter, r *http.Request) {
	nClusters := queryInt(r, "n_clusters", 12)
	limit := queryInt(r, "limit", 5000)
	perCluster := queryInt(r, "papers_per_cluster", 5)
	ids, vecs, topicOf := s.loadVectors(limit, "")
	if len(vecs) < 10 {
		writeJSON(w, http.StatusOK, map[string]any{"clusters": []any{}, "message": "有效向量不足"})
		return
	}
	assign := kmeans(vecs, nClusters, 10)
	groups := map[int][]int{}
	for i, c := range assign {
		groups[c] = append(groups[c], i)
	}
	clusters := []map[string]any{}
	clusterID := 0
	totalPapers := 0
	for _, idxs := range groups {
		clusterID++
		// 主题标签（成员多数主题）
		counts := map[string]int{}
		for _, i := range idxs {
			for _, tn := range topicOf[ids[i]] {
				counts[tn]++
			}
		}
		name := "未命名领域"
		keywords := []string{}
		maxN := 0
		for tn, c := range counts {
			if c > maxN {
				maxN, name = c, tn
			}
		}
		if name != "未命名领域" {
			keywords = append(keywords, name)
		}
		papers := make([]map[string]any, 0, perCluster)
		for k, i := range idxs {
			if k >= perCluster {
				break
			}
			var title, arxiv, abstract string
			_ = s.db.QueryRow(`SELECT COALESCE(title,''), COALESCE(arxiv_id,''), COALESCE(abstract,'') FROM papers WHERE id=$1`, ids[i]).Scan(&title, &arxiv, &abstract)
			if len(abstract) > 200 {
				abstract = abstract[:200]
			}
			papers = append(papers, map[string]any{
				"id": ids[i], "title": title, "arxiv_id": arxiv, "abstract": abstract,
			})
		}
		totalPapers += len(idxs)
		clusters = append(clusters, map[string]any{
			"cluster_id": clusterID, "name": name, "keywords": keywords,
			"size": len(idxs), "papers": papers,
		})
	}
	sort.Slice(clusters, func(i, j int) bool { return clusters[i]["size"].(int) > clusters[j]["size"].(int) })
	writeJSON(w, http.StatusOK, map[string]any{
		"clusters": clusters, "total_clusters": len(clusters), "total_papers": totalPapers,
	})
}

// handleSimilarViaCitation GET /graph/similar-via-citation/{paper_id}。
// 契约：SimilarViaCitationResponse{paper_id, items:[SimilarityItem{id,title,arxiv_id,similarity}], count}。
func (s *Server) handleSimilarViaCitation(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	topK := queryInt(r, "top_k", 5)
	rows, err := s.db.Query(
		`SELECT c2.source_paper_id, COUNT(*) AS shared FROM citations c1
		 JOIN citations c2 ON c2.target_paper_id = c1.target_paper_id
		 WHERE c1.source_paper_id=$1 AND c2.source_paper_id != $1
		 GROUP BY c2.source_paper_id ORDER BY shared DESC LIMIT $2`, paperID, topK)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	maxShared := 1
	for rows.Next() {
		var pid string
		var shared int
		if rows.Scan(&pid, &shared) == nil {
			if shared > maxShared {
				maxShared = shared
			}
			var title, arxiv string
			_ = s.db.QueryRow(`SELECT COALESCE(title,''), COALESCE(arxiv_id,'') FROM papers WHERE id=$1`, pid).Scan(&title, &arxiv)
			items = append(items, map[string]any{
				"id": pid, "title": title, "arxiv_id": strOrNull(arxiv),
				"similarity": 0, // 占位——下面归一化
				"_shared":    shared,
			})
		}
	}
	for _, it := range items {
		shared := it["_shared"].(int)
		it["similarity"] = math.Round(float64(shared)/float64(maxShared)*100) / 100
		delete(it, "_shared")
	}
	writeJSON(w, http.StatusOK, map[string]any{"paper_id": paperID, "items": items, "count": len(items)})
}

// ---------- LLM 图谱端点（survey / evolution / researchGaps）----------

// graphPaperLite 轻量论文条目（上下文构造用）。
type graphPaperLite struct {
	id, title, year, summary string
}

// keywordFilterSQL 关键词匹配：标题/摘要 LIKE + 分类标签 + 订阅主题名。
// 洞察面板用主题名（如 cs.AI）当关键词——只匹配标题会得到空集。
const keywordFilterSQL = `(LOWER(p.title) LIKE LOWER($%d) OR LOWER(p.abstract) LIKE LOWER($%d)
		   OR p.metadata->'categories' ? $%d
		   OR EXISTS (SELECT 1 FROM paper_topics pt JOIN topic_subscriptions t ON t.id = pt.topic_id
		              WHERE pt.paper_id = p.id AND LOWER(t.name) = LOWER($%d)))`

// papersForLLM 关键词匹配论文（标题/摘要/分类/主题），带精读摘要。
func (s *Server) papersForLLM(keyword string, limit int) []graphPaperLite {
	pattern := "%" + keyword + "%"
	rows, err := s.db.Query(
		`SELECT p.id, p.title, COALESCE(TO_CHAR(p.publication_date,'YYYY'),''), COALESCE(ar.summary_md,'')
		 FROM papers p LEFT JOIN analysis_reports ar ON ar.paper_id = p.id
		 WHERE `+fmt.Sprintf(keywordFilterSQL, 1, 2, 3, 4)+`
		 ORDER BY p.created_at DESC LIMIT $5`, pattern, pattern, keyword, keyword, limit)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var out []graphPaperLite
	for rows.Next() {
		var p graphPaperLite
		if rows.Scan(&p.id, &p.title, &p.year, &p.summary) == nil {
			if len(p.summary) > 300 {
				p.summary = p.summary[:300]
			}
			out = append(out, p)
		}
	}
	return out
}

// paperIDsForKeyword 关键词命中的论文 ID 集（network_stats 用）。
func (s *Server) paperIDsForKeyword(keyword string, limit int) []string {
	pattern := "%" + keyword + "%"
	rows, err := s.db.Query(
		`SELECT id FROM papers p WHERE `+fmt.Sprintf(keywordFilterSQL, 1, 2, 3, 4)+` LIMIT $5`,
		pattern, pattern, keyword, keyword, limit)
	if err != nil {
		return nil
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if rows.Scan(&id) == nil {
			ids = append(ids, id)
		}
	}
	return ids
}

// networkStats 前端 network_stats 契约。
func (s *Server) networkStats(ids []string) map[string]any {
	idSet := map[string]bool{}
	for _, id := range ids {
		idSet[id] = true
	}
	edgeCount := 0
	connected := map[string]bool{}
	for _, e := range s.loadGraphEdges() {
		if idSet[e.Source] && idSet[e.Target] {
			edgeCount++
			connected[e.Source], connected[e.Target] = true, true
		}
	}
	isolated := len(ids) - len(connected)
	n := len(ids)
	density := 0.0
	if n > 1 {
		density = math.Round(float64(edgeCount)/float64(n*(n-1))*1e6) / 1e6
	}
	ratio := 0.0
	if n > 0 {
		ratio = math.Round(float64(len(connected))/float64(n)*1e4) / 1e4
	}
	return map[string]any{
		"total_papers": n, "edge_count": edgeCount, "density": density,
		"connected_ratio": ratio, "isolated_count": isolated,
	}
}

// handleGraphSurvey GET /graph/survey。
// 契约：SurveyResponse{keyword, summary{overview, stages:string[], reading_list[], open_questions[]}, milestones, seminal}。
func (s *Server) handleGraphSurvey(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	if keyword == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "keyword required"})
		return
	}
	limit := queryInt(r, "limit", 120)
	papers := s.papersForLLM(keyword, 30)
	var lines []string
	for _, p := range papers {
		lines = append(lines, fmt.Sprintf("- [%s] %s: %s", p.year, p.title, p.summary))
	}
	prompt := fmt.Sprintf(`你是科研综述作者。请基于以下论文列表，为主题「%s」生成领域综述，输出严格 JSON：
{"overview":"领域概述（300-600字）","stages":["发展阶段一（1990-2005）：说明","发展阶段二：说明"],"reading_list":["必读论文标题1"],"open_questions":["开放问题1"]}

论文列表:
%s`, keyword, strings.Join(lines, "\n"))
	cacheKey := "survey:" + keyword + ":" + fmt.Sprint(limit)
	if cached, ok := llmCacheGet(cacheKey); ok {
		writeJSON(w, http.StatusOK, cached)
		return
	}
	parsed, _, err := s.GW().CompleteJSON(r.Context(), "deep", prompt)
	if err != nil || parsed == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "LLM 生成失败"})
		return
	}
	tl := s.buildTimeline(keyword, 20)
	resp := map[string]any{
		"keyword": keyword,
		"summary": map[string]any{
			"overview":       strOf(parsed["overview"]),
			"stages":         orSliceAny(parsed["stages"]),
			"reading_list":   orSliceAny(parsed["reading_list"]),
			"open_questions": orSliceAny(parsed["open_questions"]),
		},
		"milestones": tl["milestones"],
		"seminal":    tl["seminal"],
	}
	llmCacheSet(cacheKey, resp, 5*time.Minute)
	writeJSON(w, http.StatusOK, resp)
}

// buildTimeline 构造 TimelineResponse 主体（survey 复用）。
func (s *Server) buildTimeline(keyword string, limit int) map[string]any {
	_ = keyword
	papers := s.loadGraphPapers(2000)
	edges := s.loadGraphEdges()
	idSet := map[string]bool{}
	for _, p := range papers {
		idSet[p.ID] = true
	}
	valid := []graphEdge{}
	for _, e := range edges {
		if idSet[e.Source] && idSet[e.Target] {
			valid = append(valid, e)
		}
	}
	pr := core.PageRank(keys(idSet), edgePairs(valid))
	inDeg := map[string]int{}
	for _, e := range valid {
		inDeg[e.Target]++
	}
	type item struct {
		paper graphPaper
		score float64
		inDeg int
	}
	var items []item
	for _, p := range papers {
		items = append(items, item{p, pr[p.ID], inDeg[p.ID]})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].score > items[j].score })
	toEntry := func(it item) map[string]any {
		year := 0
		if it.paper.Year != nil {
			year = *it.paper.Year
		}
		return map[string]any{
			"paper_id": it.paper.ID, "title": it.paper.Title, "year": year,
			"indegree": it.inDeg, "outdegree": 0,
			"pagerank":      math.Round(it.score*1e4) / 1e4,
			"seminal_score": math.Round(it.score*1e3) / 1e3,
		}
	}
	timeline := []map[string]any{}
	n := len(items)
	if n > limit {
		n = limit
	}
	for i := 0; i < n; i++ {
		timeline = append(timeline, toEntry(items[i]))
	}
	seminal := timeline
	if len(seminal) > 20 {
		seminal = seminal[:20]
	}
	best := map[int]map[string]any{}
	var years []int
	for _, e := range timeline {
		y, _ := e["year"].(int)
		if y == 0 {
			continue
		}
		if _, ok := best[y]; !ok {
			years = append(years, y)
			best[y] = e
		}
	}
	sort.Ints(years)
	milestones := []map[string]any{}
	for _, y := range years {
		milestones = append(milestones, best[y])
	}
	return map[string]any{"timeline": timeline, "seminal": seminal, "milestones": milestones}
}

// handleWeeklyEvolution GET /graph/evolution/weekly。
// 契约：EvolutionResponse{keyword, year_buckets:[YearBucket], summary{trend_summary, phase_shift_signals, next_week_focus}}。
func (s *Server) handleWeeklyEvolution(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	if keyword == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "keyword required"})
		return
	}
	limit := queryInt(r, "limit", 160)
	_ = limit
	papers := s.papersForLLM(keyword, 60)
	// year_buckets：按年聚合
	bucket := map[int][]graphPaperLite{}
	var years []int
	for _, p := range papers {
		y := 0
		fmt.Sscanf(p.year, "%d", &y)
		if y == 0 {
			continue
		}
		if _, ok := bucket[y]; !ok {
			years = append(years, y)
		}
		bucket[y] = append(bucket[y], p)
	}
	sort.Ints(years)
	yearBuckets := []map[string]any{}
	var contextLines []string
	for _, y := range years {
		list := bucket[y]
		topTitles := []string{}
		for i, p := range list {
			if i >= 3 {
				break
			}
			topTitles = append(topTitles, p.title)
		}
		yearBuckets = append(yearBuckets, map[string]any{
			"year": y, "paper_count": len(list),
			"avg_seminal_score": 0, "top_titles": topTitles,
		})
		for i, p := range list {
			if i >= 2 {
				break
			}
			contextLines = append(contextLines, fmt.Sprintf("- [%s] %s", p.year, p.title))
		}
	}
	prompt := fmt.Sprintf(`你是研究趋势分析师。请分析主题「%s」的论文时间分布与动态，输出严格 JSON：
{"trend_summary":"趋势总结（200-400字）","phase_shift_signals":"阶段转变信号说明","next_week_focus":"下一步建议关注的焦点"}

论文时间线:
%s`, keyword, strings.Join(contextLines, "\n"))
	cacheKey := "evolution:" + keyword + ":" + fmt.Sprint(limit)
	if cached, ok := llmCacheGet(cacheKey); ok {
		writeJSON(w, http.StatusOK, cached)
		return
	}
	parsed, _, err := s.GW().CompleteJSON(r.Context(), "deep", prompt)
	if err != nil || parsed == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "LLM 生成失败"})
		return
	}
	resp := map[string]any{
		"keyword":      keyword,
		"year_buckets": yearBuckets,
		"summary": map[string]any{
			"trend_summary":       strOf(parsed["trend_summary"]),
			"phase_shift_signals": strOf(parsed["phase_shift_signals"]),
			"next_week_focus":     strOf(parsed["next_week_focus"]),
		},
	}
	llmCacheSet(cacheKey, resp, 5*time.Minute)
	writeJSON(w, http.StatusOK, resp)
}

// handleResearchGaps GET /graph/research-gaps。
// 契约：ResearchGapsResponse{keyword, network_stats, analysis{research_gaps[ResearchGap], method_comparison, trend_analysis, overall_summary}}。
func (s *Server) handleResearchGaps(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	if keyword == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "keyword required"})
		return
	}
	limit := queryInt(r, "limit", 120)
	ids := s.paperIDsForKeyword(keyword, limit)
	stats := s.networkStats(ids)
	papers := s.papersForLLM(keyword, 30)
	var lines []string
	for _, p := range papers {
		lines = append(lines, fmt.Sprintf("- [%s] %s: %s", p.year, p.title, p.summary))
	}
	prompt := fmt.Sprintf(`你是研究策略顾问。请基于主题「%s」的论文列表识别研究空白，输出严格 JSON：
{"research_gaps":[{"gap_title":"空白标题","description":"描述","evidence":"佐证（引用具体论文）","potential_impact":"潜在影响","suggested_approach":"建议方法","difficulty":"easy|medium|hard","confidence":0.8}],
 "method_comparison":{"dimensions":["维度1"],"methods":[{"name":"方法名","scores":{"维度1":"高"},"papers":["论文名"]}],"underexplored_combinations":["未充分探索的组合"]},
 "trend_analysis":{"hot_directions":["热点方向"],"declining_areas":["衰退领域"],"emerging_opportunities":["新兴机会"]},
 "overall_summary":"总体总结（150-300字）"}

论文列表:
%s`, keyword, strings.Join(lines, "\n"))
	cacheKey := "gaps:" + keyword + ":" + fmt.Sprint(limit)
	if cached, ok := llmCacheGet(cacheKey); ok {
		writeJSON(w, http.StatusOK, cached)
		return
	}
	parsed, _, err := s.GW().CompleteJSON(r.Context(), "deep", prompt)
	if err != nil || parsed == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "LLM 生成失败"})
		return
	}
	resp := map[string]any{
		"keyword":       keyword,
		"network_stats": stats,
		"analysis": map[string]any{
			"research_gaps":     orSliceAny(parsed["research_gaps"]),
			"method_comparison": parsed["method_comparison"],
			"trend_analysis":    parsed["trend_analysis"],
			"overall_summary":   strOf(parsed["overall_summary"]),
		},
	}
	llmCacheSet(cacheKey, resp, 10*time.Minute)
	writeJSON(w, http.StatusOK, resp)
}


// keys map 键切片。
func keys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

// handleSyncCitationsIncremental POST /citations/sync/incremental。
func (s *Server) handleSyncCitationsIncremental(w http.ResponseWriter, r *http.Request) {
	jobID, taskID, err := s.submitCoreTask("sync_citations_incremental", map[string]any{
		"paper_limit": 40, "edge_limit_per_paper": 6,
	}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleSyncCitationsTopic POST /citations/sync/topic/{topic_id}。
func (s *Server) handleSyncCitationsTopic(w http.ResponseWriter, r *http.Request) {
	topicID := r.PathValue("topic_id")
	jobID, taskID, err := s.submitCoreTask("sync_citations_topic", map[string]any{
		"topic_id": topicID, "paper_limit": 30, "edge_limit_per_paper": 6,
	}, 1800)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}

// handleSyncCitationsPaper POST /citations/sync/{paper_id}。
func (s *Server) handleSyncCitationsPaper(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	jobID, taskID, err := s.submitCoreTask("sync_citations_paper", map[string]any{
		"paper_id": paperID, "limit": 8,
	}, 600)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"task_id": taskID, "job_id": jobID, "status": "queued"})
}
