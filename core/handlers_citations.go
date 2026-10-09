// 引用图谱处理器：sync_citations_paper / incremental / topic。
// S2 网络抓取留 handler，papers upsert + 边 upsert 在权威面单事务 apply
// （applyCitationEdgesResult）。
package core

import (
	"context"
	"errors"
	"fmt"
)

// citationEdgesProposal citation_edges proposal 公共封装（标题 → ss- 合成键，
// 与旧路径 _title_to_id 一致）。
func citationEdgesProposal(paperID string, edges []CitationEdge) map[string]any {
	items := make([]any, len(edges))
	for i, e := range edges {
		items[i] = map[string]any{
			"source": map[string]any{
				"arxiv_id": titleToID(e.SourceTitle), "title": e.SourceTitle,
				"abstract": "", "metadata": map[string]any{"source": "semantic_scholar"},
			},
			"target": map[string]any{
				"arxiv_id": titleToID(e.TargetTitle), "title": e.TargetTitle,
				"abstract": "", "metadata": map[string]any{"source": "semantic_scholar"},
			},
			"context": e.Context,
		}
	}
	return map[string]any{
		"proposal": map[string]any{"kind": "citation_edges", "paper_id": paperID, "edges": items},
	}
}

// fetchEdgesForPaper 单篇引用边候选抓取（读库定位标题 → S2）。
func fetchEdgesForPaper(ctx context.Context, env *HandlerEnv, paperID string, limit int) ([]CitationEdge, error) {
	var title string
	if err := env.Store.DB.QueryRow(`SELECT title FROM papers WHERE id=$1`, paperID).Scan(&title); err != nil {
		return nil, fmt.Errorf("论文 %s 不存在", paperID)
	}
	return env.Scholar.FetchEdgesByTitle(ctx, title, limit)
}

// ---------- sync_citations_paper ----------

func HandleSyncCitationsPaper(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	paperID, _ := task.Input["paper_id"].(string)
	limit := intOf(task.Input["limit"], 8)
	if limit <= 0 {
		limit = 8
	}
	if paperID == "" {
		return nil, errors.New("缺少 paper_id")
	}
	edges, err := fetchEdgesForPaper(ctx, env, paperID, limit)
	if err != nil {
		return nil, err
	}
	return citationEdgesProposal(paperID, edges), nil
}

// ---------- sync_citations_incremental ----------

func HandleSyncCitationsIncremental(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	paperLimit := intOf(task.Input["paper_limit"], 40)
	edgeLimit := intOf(task.Input["edge_limit_per_paper"], 6)
	if paperLimit <= 0 {
		paperLimit = 40
	}
	if edgeLimit <= 0 {
		edgeLimit = 6
	}

	// 选取无引用边的最新论文（与 Python 选择器语义一致）
	rows, err := env.Store.DB.Query(
		`SELECT p.id, COALESCE(p.title, '') FROM papers p
		 WHERE p.id NOT IN (
		   SELECT source_paper_id FROM citations
		   UNION SELECT target_paper_id FROM citations)
		 ORDER BY p.created_at DESC LIMIT $1`, paperLimit)
	if err != nil {
		return nil, err
	}
	type pidTitle struct{ id, title string }
	var targets []pidTitle
	for rows.Next() {
		var t pidTitle
		if rows.Scan(&t.id, &t.title) == nil {
			targets = append(targets, t)
		}
	}
	rows.Close()

	allEdges := []CitationEdge{}
	for _, t := range targets {
		edges, err := env.Scholar.FetchEdgesByTitle(ctx, t.title, edgeLimit)
		if err != nil {
			continue // 单篇失败不阻断
		}
		allEdges = append(allEdges, edges...)
	}
	proposal := citationEdgesProposal("", allEdges)["proposal"].(map[string]any)
	ids := make([]any, len(targets))
	for i, t := range targets {
		ids[i] = t.id
	}
	proposal["paper_ids"] = ids
	return map[string]any{"proposal": proposal}, nil
}

// ---------- sync_citations_topic ----------

func HandleSyncCitationsTopic(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	topicID, _ := task.Input["topic_id"].(string)
	paperLimit := intOf(task.Input["paper_limit"], 30)
	edgeLimit := intOf(task.Input["edge_limit_per_paper"], 6)
	if paperLimit <= 0 {
		paperLimit = 30
	}
	if edgeLimit <= 0 {
		edgeLimit = 6
	}
	if topicID == "" {
		return nil, errors.New("缺少 topic_id")
	}

	var exists string
	if err := env.Store.DB.QueryRow(`SELECT id FROM topic_subscriptions WHERE id=$1`, topicID).Scan(&exists); err != nil {
		return nil, fmt.Errorf("topic %s not found", topicID)
	}
	rows, err := env.Store.DB.Query(
		`SELECT p.id, COALESCE(p.title, '') FROM papers p
		 JOIN paper_topics pt ON pt.paper_id = p.id
		 WHERE pt.topic_id=$1 ORDER BY p.created_at DESC LIMIT $2`, topicID, paperLimit)
	if err != nil {
		return nil, err
	}
	type pidTitle struct{ id, title string }
	var papers []pidTitle
	for rows.Next() {
		var t pidTitle
		if rows.Scan(&t.id, &t.title) == nil {
			papers = append(papers, t)
		}
	}
	rows.Close()

	allEdges := []CitationEdge{}
	for _, t := range papers {
		edges, err := env.Scholar.FetchEdgesByTitle(ctx, t.title, edgeLimit)
		if err != nil {
			continue // 单篇失败不阻断
		}
		allEdges = append(allEdges, edges...)
	}
	proposal := citationEdgesProposal(topicID, allEdges)["proposal"].(map[string]any)
	proposal["topic_id"] = topicID
	return map[string]any{"proposal": proposal}, nil
}
