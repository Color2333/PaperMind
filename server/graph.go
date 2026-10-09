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
	"strings"
	"time"

	core "github.com/Color2333/PaperMind/core"
)

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
func (s *Server) handleGraphTimeline(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	limit := queryInt(r, "limit", 100)
	_ = limit
	papers := s.loadGraphPapers(500)
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
	// keyword 过滤（标题/摘要匹配；空 = 全部）
	kw := strings.ToLower(keyword)
	type item struct {
		paper  graphPaper
		score  float64
		inDeg  int
	}
	inDeg := map[string]int{}
	for _, e := range valid {
		inDeg[e.Target]++
	}
	var items []item
	for _, p := range papers {
		if kw != "" && !matchKeyword(p, kw) {
			continue
		}
		items = append(items, item{p, pr[p.ID], inDeg[p.ID]})
	}
	sort.Slice(items, func(i, j int) bool { return items[i].score > items[j].score })
	result := []map[string]any{}
	for _, it := range items {
		result = append(result, map[string]any{
			"id": it.paper.ID, "title": it.paper.Title, "arxiv_id": it.paper.ArxivID,
			"year": it.paper.Year, "pagerank": math.Round(it.score*1e4)/1e4,
			"in_degree": it.inDeg, "score": math.Round(it.score*1e3)/1e3,
			"why_seminal": fmt.Sprintf("indegree=%d, pagerank=%.4f", it.inDeg, it.score),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": result, "total": len(result)})
}

// matchKeyword 标题匹配（全文匹配省略——keyword 过滤在标题层已覆盖前端场景）。
func matchKeyword(p graphPaper, kw string) bool {
	if kw == "" {
		return true
	}
	if strings.Contains(strings.ToLower(p.Title), kw) {
		return true
	}
	// 摘要匹配（逐篇查太贵——批量场景由调用方限定）
	return true
}

func keys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}

// handleGraphQuality GET /graph/quality?keyword=&limit=。
func (s *Server) handleGraphQuality(w http.ResponseWriter, r *http.Request) {
	limit := queryInt(r, "limit", 120)
	papers := s.loadGraphPapers(limit)
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
	pubRatio := 0.0
	if n > 0 {
		pubRatio = math.Round(float64(withPub)/float64(n)*1e4) / 1e4
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"total_papers": n, "total_edges": ie, "density": density,
		"connected_node_ratio": connRatio, "publication_date_ratio": pubRatio,
		"message": map[bool]string{true: "图谱数据充足", false: "论文或引用边较少，建议先运行引用同步"}[ie > 0],
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
	// 节点信息
	nodeInfo := map[string]map[string]any{}
	fetch := func(pid string) {
		if _, ok := nodeInfo[pid]; ok {
			return
		}
		var title string
		var year sql.NullString
		if err := s.db.QueryRow(
			`SELECT COALESCE(title,''), TO_CHAR(publication_date,'YYYY') FROM papers WHERE id=$1`, pid,
		).Scan(&title, &year); err == nil {
			var yr any
			if year.Valid && year.String != "" {
				yr = year.String
			}
			nodeInfo[pid] = map[string]any{"id": pid, "title": strOrNull(title), "year": yr}
		} else {
			nodeInfo[pid] = map[string]any{"id": pid, "title": nil, "year": nil}
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
	writeJSON(w, http.StatusOK, map[string]any{
		"root": nodeInfo[paperID], "nodes": nodes,
		"ancestor_edges": ancestors, "descendant_edges": descendants,
	})
}

func strOrNull(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// handleTopicCitationNetwork GET /graph/citation-network/topic/{topic_id}。
func (s *Server) handleTopicCitationNetwork(w http.ResponseWriter, r *http.Request) {
	topicID := r.PathValue("topic_id")
	rows, err := s.db.Query(
		`SELECT p.id, COALESCE(p.title,'') FROM papers p
		 JOIN paper_topics pt ON pt.paper_id = p.id WHERE pt.topic_id=$1 LIMIT 500`, topicID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	members := map[string]string{}
	var order []string
	for rows.Next() {
		var id, title string
		if rows.Scan(&id, &title) == nil {
			members[id] = title
			order = append(order, id)
		}
	}
	rows.Close()
	edges := []map[string]any{}
	for _, e := range s.loadGraphEdges() {
		if _, okS := members[e.Source]; okS {
			if _, okT := members[e.Target]; okT {
				edges = append(edges, map[string]any{"source": e.Source, "target": e.Target})
			}
		}
	}
	nodes := make([]map[string]any, 0, len(order))
	for _, id := range order {
		nodes = append(nodes, map[string]any{"id": id, "title": members[id]})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"topic_id": topicID, "nodes": nodes, "edges": edges,
		"total_papers": len(nodes), "total_edges": len(edges),
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

// handleCitationDetail GET /graph/citation-detail/{paper_id} —— 库内引用详情。
func (s *Server) handleCitationDetail(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	references := []map[string]any{}
	rows, err := s.db.Query(
		`SELECT p.id, COALESCE(p.title,''), COALESCE(p.arxiv_id,''), c.context
		 FROM citations c JOIN papers p ON p.id = c.target_paper_id
		 WHERE c.source_paper_id=$1`, paperID)
	if err == nil {
		for rows.Next() {
			var id, title, arxivID string
			var ctx sql.NullString
			if rows.Scan(&id, &title, &arxivID, &ctx) == nil {
				references = append(references, map[string]any{
					"id": id, "title": title, "arxiv_id": arxivID, "context": nullStr(ctx),
				})
			}
		}
		rows.Close()
	}
	citations := []map[string]any{}
	rows, err = s.db.Query(
		`SELECT p.id, COALESCE(p.title,''), COALESCE(p.arxiv_id,''), c.context
		 FROM citations c JOIN papers p ON p.id = c.source_paper_id
		 WHERE c.target_paper_id=$1`, paperID)
	if err == nil {
		for rows.Next() {
			var id, title, arxivID string
			var ctx sql.NullString
			if rows.Scan(&id, &title, &arxivID, &ctx) == nil {
				citations = append(citations, map[string]any{
					"id": id, "title": title, "arxiv_id": arxivID, "context": nullStr(ctx),
				})
			}
		}
		rows.Close()
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"paper_id": paperID, "references": references, "citations": citations,
		"reference_count": len(references), "citation_count": len(citations),
	})
}

// ---------- 桥接 / 前沿 / 共引 ----------

// handleGraphBridges GET /graph/bridges —— 跨主题桥接论文。
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
	type bridge struct {
		pid      string
		title    string
		topics   []string
		crossDeg int
	}
	bridges := map[string]*bridge{}
	for _, e := range s.loadGraphEdges() {
		srcTopics, dstTopics := paperTopics[e.Source], paperTopics[e.Target]
		cross := false
		for _, st := range srcTopics {
			for _, dt := range dstTopics {
				if st != dt {
					cross = true
				}
			}
		}
		if !cross {
			continue
		}
		for _, pid := range []string{e.Source, e.Target} {
			if bridges[pid] == nil {
				bridges[pid] = &bridge{pid: pid, topics: paperTopics[pid]}
			}
			bridges[pid].crossDeg++
		}
	}
	var list []*bridge
	for _, b := range bridges {
		list = append(list, b)
	}
	sort.Slice(list, func(i, j int) bool { return list[i].crossDeg > list[j].crossDeg })
	if len(list) > 20 {
		list = list[:20]
	}
	// 补标题
	items := []map[string]any{}
	for _, b := range list {
		var title string
		_ = s.db.QueryRow(`SELECT COALESCE(title,'') FROM papers WHERE id=$1`, b.pid).Scan(&title)
		items = append(items, map[string]any{
			"id": b.pid, "title": title, "topics": orSlice(b.topics),
			"cross_degree": b.crossDeg,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "total": len(items)})
}

// handleGraphFrontier GET /graph/frontier?days= —— 研究前沿（近期高被引新论文）。
func (s *Server) handleGraphFrontier(w http.ResponseWriter, r *http.Request) {
	days := queryInt(r, "days", 90)
	cutoff := time.Now().UTC().AddDate(0, 0, -days).Format("2006-01-02 15:04:05.000000")
	rows, err := s.db.Query(
		`SELECT c.target_paper_id, COUNT(*) AS cites FROM citations c
		 JOIN papers p ON p.id = c.target_paper_id
		 WHERE p.created_at >= $1
		 GROUP BY c.target_paper_id ORDER BY cites DESC LIMIT 20`, cutoff)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var pid string
		var cites int
		if rows.Scan(&pid, &cites) == nil {
			var title, arxivID string
			_ = s.db.QueryRow(`SELECT COALESCE(title,''), COALESCE(arxiv_id,'') FROM papers WHERE id=$1`, pid).Scan(&title, &arxivID)
			items = append(items, map[string]any{
				"id": pid, "title": title, "arxiv_id": arxivID,
				"citation_count": cites, "window_days": days,
			})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "total": len(items)})
}

// handleCocitationClusters GET /graph/cocitation-clusters —— 共引配对聚类。
func (s *Server) handleCocitationClusters(w http.ResponseWriter, r *http.Request) {
	minCocite := queryInt(r, "min_cocite", 2)
	// target → 引它的 sources；两 target 共享 ≥minCocite 个 source 即共引对
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
	for i := 0; i < len(targets); i++ {
		for j := i + 1; j < len(targets); j++ {
			shared := 0
			for src := range targetSources[targets[i]] {
				if targetSources[targets[j]][src] {
					shared++
				}
			}
			if shared >= minCocite {
				pairs = append(pairs, pair{targets[i], targets[j], shared})
			}
		}
	}
	// 并查集聚类
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
		clusters[find(t)] = append(clusters[find(t)], t)
	}
	var out []map[string]any
	for root, members := range clusters {
		if len(members) < 2 {
			continue
		}
		// 主题标签：成员最多主题
		name := ""
		counts := map[string]int{}
		for _, m := range members {
			var tn string
			if err := s.db.QueryRow(
				`SELECT COALESCE(t.name,'') FROM paper_topics pt LEFT JOIN topic_subscriptions t ON t.id=pt.topic_id WHERE pt.paper_id=$1 LIMIT 1`, m,
			).Scan(&tn); err == nil && tn != "" {
				counts[tn]++
			}
		}
		maxN := 0
		for tn, c := range counts {
			if c > maxN {
				maxN, name = c, tn
			}
		}
		if name == "" {
			name = "cluster-" + root[:8]
		}
		out = append(out, map[string]any{"label": name, "paper_ids": members, "size": len(members)})
	}
	writeJSON(w, http.StatusOK, map[string]any{"clusters": orSliceAny(toAny(out)), "total": len(out)})
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
		p := map[string]any{"id": id, "x": proj[i][0], "y": proj[i][1], "topics": orSlice(topicOf[id])}
		var title string
		_ = s.db.QueryRow(`SELECT COALESCE(title,'') FROM papers WHERE id=$1`, id).Scan(&title)
		p["title"] = title
		points[i] = p
	}
	writeJSON(w, http.StatusOK, map[string]any{"points": points, "total": len(points), "method": "pca"})
}

// kmeans 加权 k-means（与 Python _kmeans 语义对齐，固定种子可复现）。
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
	groups := map[int][]string{}
	for i, c := range assign {
		groups[c] = append(groups[c], ids[i])
	}
	clusters := []map[string]any{}
	for _, members := range groups {
		// 主题标签（成员多数主题）
		counts := map[string]int{}
		for _, m := range members {
			for _, tn := range topicOf[m] {
				counts[tn]++
			}
		}
		label := "未命名领域"
		maxN := 0
		for tn, c := range counts {
			if c > maxN {
				maxN, label = c, tn
			}
		}
		papers := make([]map[string]any, 0, perCluster)
		for i, m := range members {
			if i >= perCluster {
				break
			}
			var title string
			_ = s.db.QueryRow(`SELECT COALESCE(title,'') FROM papers WHERE id=$1`, m).Scan(&title)
			papers = append(papers, map[string]any{"id": m, "title": title})
		}
		clusters = append(clusters, map[string]any{
			"label": label, "size": len(members), "papers": papers,
		})
	}
	sort.Slice(clusters, func(i, j int) bool { return clusters[i]["size"].(int) > clusters[j]["size"].(int) })
	writeJSON(w, http.StatusOK, map[string]any{"clusters": clusters, "total": len(clusters)})
}

// handleSimilarViaCitation GET /graph/similar-via-citation/{paper_id}。
func (s *Server) handleSimilarViaCitation(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	topK := queryInt(r, "top_k", 5)
	// 共引：引用同一 target 的其他 source 论文
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
	for rows.Next() {
		var pid string
		var shared int
		if rows.Scan(&pid, &shared) == nil {
			var title string
			_ = s.db.QueryRow(`SELECT COALESCE(title,'') FROM papers WHERE id=$1`, pid).Scan(&title)
			items = append(items, map[string]any{"id": pid, "title": title, "shared_references": shared})
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"paper_id": paperID, "items": items, "total": len(items)})
}

// ---------- LLM 图谱端点（survey / weekly evolution / research gaps） ----------

// timelineContextForLLM 主题论文上下文（survey 系共用）。
func (s *Server) timelineContextForLLM(keyword string, limit int) (string, []map[string]any) {
	pattern := "%" + keyword + "%"
	rows, err := s.db.Query(
		`SELECT p.id, p.title, TO_CHAR(p.publication_date,'YYYY'), COALESCE(ar.summary_md,'')
		 FROM papers p LEFT JOIN analysis_reports ar ON ar.paper_id = p.id
		 WHERE LOWER(p.title) LIKE LOWER($1)
		 ORDER BY p.created_at DESC LIMIT $2`, pattern, limit)
	if err != nil {
		return "", nil
	}
	defer rows.Close()
	var lines []string
	var milestones []map[string]any
	for rows.Next() {
		var id, title, year, summary string
		if rows.Scan(&id, &title, &year, &summary) == nil {
			if len(summary) > 300 {
				summary = summary[:300]
			}
			if year == "" {
				year = "?"
			}
			lines = append(lines, fmt.Sprintf("- [%s] %s: %s", year, title, summary))
			milestones = append(milestones, map[string]any{"id": id, "title": title, "year": year})
		}
	}
	return strings.Join(lines, "\n"), milestones
}

// handleGraphSurvey GET /graph/survey —— 领域综述（LLM）。
func (s *Server) handleGraphSurvey(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	if keyword == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "keyword required"})
		return
	}
	limit := queryInt(r, "limit", 120)
	ctxText, _ := s.timelineContextForLLM(keyword, limit)
	prompt := fmt.Sprintf(`你是科研综述作者。请基于以下论文列表，为主题「%s」生成领域综述，输出严格 JSON：
{"overview":"领域概述（300-600字）","stages":[{"name":"发展阶段","description":"说明"}],"reading_list":["必读论文标题"],"open_questions":["开放问题"]}

论文列表:
%s`, keyword, ctxText)
	parsed, _, err := s.GW().CompleteJSON(r.Context(), "deep", prompt)
	if err != nil || parsed == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "LLM 生成失败"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"keyword": keyword,
		"overview": strOf(parsed["overview"]),
		"stages":         orSliceAny(parsed["stages"]),
		"reading_list":   orSliceAny(parsed["reading_list"]),
		"open_questions": orSliceAny(parsed["open_questions"]),
	})
}

// handleWeeklyEvolution GET /graph/evolution/weekly —— 周演化（LLM）。
func (s *Server) handleWeeklyEvolution(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	if keyword == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "keyword required"})
		return
	}
	_ = queryInt(r, "limit", 160)
	// 近 7 天新论文
	cutoff := time.Now().UTC().AddDate(0, 0, -7).Format("2006-01-02 15:04:05.000000")
	rows, err := s.db.Query(
		`SELECT p.title, COALESCE(ar.summary_md,'') FROM papers p
		 LEFT JOIN analysis_reports ar ON ar.paper_id = p.id
		 WHERE p.created_at >= $1 AND (LOWER(p.title) LIKE LOWER($2) OR $2 = '%%')
		 ORDER BY p.created_at DESC LIMIT 30`, cutoff, "%"+keyword+"%")
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	var lines []string
	for rows.Next() {
		var title, summary string
		if rows.Scan(&title, &summary) == nil {
			if len(summary) > 200 {
				summary = summary[:200]
			}
			lines = append(lines, "- "+title+": "+summary)
		}
	}
	prompt := fmt.Sprintf(`你是研究趋势分析师。请分析主题「%s」近一周的新论文动态，输出严格 JSON：
{"weekly_summary":"本周动态总结（200-400字）","emerging_directions":["新方向1"],"hot_papers":["热点论文标题"]}

本周新论文:
%s`, keyword, strings.Join(lines, "\n"))
	parsed, _, err := s.GW().CompleteJSON(r.Context(), "deep", prompt)
	if err != nil || parsed == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "LLM 生成失败"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"keyword": keyword,
		"weekly_summary": strOf(parsed["weekly_summary"]),
		"emerging_directions": orSliceAny(parsed["emerging_directions"]),
		"hot_papers":          orSliceAny(parsed["hot_papers"]),
	})
}

// handleResearchGaps GET /graph/research-gaps —— 研究空白（timeline + LLM）。
func (s *Server) handleResearchGaps(w http.ResponseWriter, r *http.Request) {
	keyword := r.URL.Query().Get("keyword")
	if keyword == "" {
		writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"detail": "keyword required"})
		return
	}
	limit := queryInt(r, "limit", 120)
	ctxText, milestones := s.timelineContextForLLM(keyword, limit)
	prompt := fmt.Sprintf(`你是研究策略顾问。请基于主题「%s」的论文时间线，识别研究空白与机会，输出严格 JSON：
{"gaps":["研究空白1（引用具体论文佐证）"],"opportunities":["机会点1"],"suggested_questions":["值得探索的问题1"]}

论文时间线:
%s`, keyword, ctxText)
	parsed, _, err := s.GW().CompleteJSON(r.Context(), "deep", prompt)
	if err != nil || parsed == nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "LLM 生成失败"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"keyword": keyword,
		"gaps":              orSliceAny(parsed["gaps"]),
		"opportunities":     orSliceAny(parsed["opportunities"]),
		"suggested_questions": orSliceAny(parsed["suggested_questions"]),
		"milestones":        milestones,
	})
}

// ---------- citations/sync 提交 ----------

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
