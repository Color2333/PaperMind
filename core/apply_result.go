// apply-result：**单一事务**提交领域变化 + fencing 校验 + Task 终态。
// （第三轮 REVIEW P0-1 的根治——proposal 模式下 Executor 不产生领域写入，
// 唯一的领域提交点在权威面，且与 fencing 校验同事务。）
package core

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// ApplyResult 按 capability 分派的 apply-result 入口（单事务）。
func (s *CoreStore) ApplyResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	var capability string
	err := s.DB.QueryRow(`SELECT capability FROM core_tasks WHERE id=$1`, taskID).Scan(&capability)
	if err != nil {
		return "", fmt.Errorf("task %s not found", taskID)
	}
	switch capability {
	case "skim_paper":
		return s.applySkimResult(taskID, executorID, leaseToken, result)
	case "deep_read_paper":
		return s.applyDeepReadResult(taskID, executorID, leaseToken, result)
	case "embed_paper":
		return s.applyEmbedResult(taskID, executorID, leaseToken, result)
	case "extract_claims":
		return s.applyExtractClaimsResult(taskID, executorID, leaseToken, result)
	case "upsert_paper":
		return s.applyUpsertPaperResult(taskID, executorID, leaseToken, result)
	case "download_source":
		return s.applyDownloadSourceResult(taskID, executorID, leaseToken, result)
	case "ingest_arxiv_query", "import_selected":
		return s.applyIngestPapersResult(taskID, executorID, leaseToken, result)
	case "generate_topic_wiki", "build_daily_brief":
		return s.applySaveGeneratedContentResult(taskID, executorID, leaseToken, result)
	case "sync_citations_paper", "sync_citations_incremental", "sync_citations_topic":
		return s.applyCitationEdgesResult(taskID, executorID, leaseToken, result)
	case "analyze_figures":
		return s.applyFigureAnalysesResult(taskID, executorID, leaseToken, result)
	case "translate_bilingual_pdf":
		return s.applyPaperTranslationResult(taskID, executorID, leaseToken, result)
	case "import_references":
		return s.applyReferenceImportResult(taskID, executorID, leaseToken, result)
	default:
		// B 档通用路径：领域写入由 handler 承载（幂等 upsert + effect ledger
		// 缓解 P0-1），Go 权威面单事务落 fencing + 终态 + result_ref 原样存储。
		// A 档升级（proposal 拆分 + Go SQL apply）按需逐项执行。
		return s.applyTerminalOnlyResult(taskID, executorID, leaseToken, result)
	}
}

// applyTerminalOnlyResult：B 档通用 apply——fencing 校验 + Task/Attempt/Job
// 终态与 result_ref 存储（不写领域表）。
func (s *CoreStore) applyTerminalOnlyResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}
	if err := finalizeTask(tx, taskID, result); err != nil {
		return "", err
	}
	if err := tx.Commit(); err != nil {
		return "", err
	}
	return "succeeded", nil
}

// fencingGuard 在事务内校验 lease 持有者 + attempt 匹配；返回 attempt fencing token。
func fencingGuard(tx *sql.Tx, taskID, executorID, leaseToken string) (int, error) {
	var status string
	var attemptCount int
	var leaseTokenDB sql.NullString
	err := tx.QueryRow(
		`SELECT status, attempt_count, lease_token FROM core_tasks WHERE id=$1`,
		taskID,
	).Scan(&status, &attemptCount, &leaseTokenDB)
	if err == sql.ErrNoRows {
		return 0, fmt.Errorf("task %s not found", taskID)
	}
	if err != nil {
		return 0, err
	}
	if status != "leased" && status != "cancelling" {
		return 0, fmt.Errorf("task %s 状态 %s 不可提交", taskID, status)
	}
	if !leaseTokenDB.Valid || leaseTokenDB.String != leaseToken {
		return 0, fmt.Errorf("task %s lease token 不匹配（迟到写入被拒绝）", taskID)
	}
	// 第四轮 P1：校验 lease 未过期（此前注释声称校验但未读取）——Reconciler
	// 扫描前，过期 Attempt 不再能提交
	var expiresAt sql.NullString
	if err := tx.QueryRow(`SELECT lease_expires_at FROM core_tasks WHERE id=$1`, taskID).Scan(&expiresAt); err == nil {
		if !expiresAt.Valid || expiresAt.String == "" || expiresAt.String <= nowParam() {
			return 0, fmt.Errorf("task %s lease 已过期（迟到提交被拒绝）", taskID)
		}
	}
	var attemptExecutor string
	err = tx.QueryRow(
		`SELECT executor_id FROM core_attempts
		 WHERE task_id=$1 AND fencing_token=$2 AND status='running'`,
		taskID, attemptCount,
	).Scan(&attemptExecutor)
	if err == sql.ErrNoRows {
		return 0, fmt.Errorf("task %s 无 running attempt（fencing token %d）", taskID, attemptCount)
	}
	if err != nil {
		return 0, err
	}
	if attemptExecutor != executorID {
		return 0, fmt.Errorf("task %s lease 属于 %s，不能由 %s 提交", taskID, attemptExecutor, executorID)
	}
	return attemptCount, nil
}

// finalizeTask 终态：Task succeeded + Attempt succeeded + Job 收敛（与领域变化同事务）
func finalizeTask(tx *sql.Tx, taskID string, result map[string]any) error {
	now := nowParam()
	// cancelling 任务的"成功完成"实为协作取消——终态 cancelled
	if _, err := tx.Exec(
		`UPDATE core_tasks SET status=CASE WHEN status='cancelling' THEN 'cancelled' ELSE 'succeeded' END,
		 lease_token=NULL, lease_expires_at=NULL, result_ref=$1 WHERE id=$2`,
		mustJSON(result), taskID,
	); err != nil {
		return err
	}
	var attemptCount int
	if err := tx.QueryRow(`SELECT attempt_count FROM core_tasks WHERE id=$1`, taskID).Scan(&attemptCount); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`UPDATE core_attempts SET status='succeeded', finished_at=$1
		 WHERE task_id=$2 AND fencing_token=$3 AND status='running'`,
		now, taskID, attemptCount,
	); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`UPDATE core_jobs SET status='succeeded', finished_at=$1 WHERE id=$2 AND status='running'`,
		now, jobIDOf(tx, taskID),
	); err != nil {
		return err
	}
	return nil
}

// applySkimResult 在单事务内：
//  1. 校验 fencing（lease_token 持有者 + attempt 匹配 + 未过期）；
//  2. 提交领域变化：analysis_reports upsert + papers read_status/metadata +
//     prompt_traces 插入；
//  3. Task → succeeded，Attempt → succeeded。
//
// 任一步失败整体回滚——迟到/重复 proposal 不会产生部分领域状态。
func (s *CoreStore) applySkimResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal（skim 切片要求 proposal 模式）")
	}
	paperID, _ := proposal["paper_id"].(string)
	skim, _ := proposal["skim"].(map[string]any)
	trace, _ := proposal["trace"].(map[string]any)
	if paperID == "" || skim == nil {
		return "", fmt.Errorf("proposal 缺少 paper_id/skim")
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	// ---- 1. fencing 校验（行锁内）----
	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	// ---- 2. 领域变化（与 Python domain_apply.apply_skim_proposal 逐字段对齐）----
	oneLiner, _ := skim["one_liner"].(string)
	relevanceScore := jsonFloat(skim["relevance_score"])
	innovations := jsonStringList(skim["innovations"])
	keywords := jsonStringList(skim["keywords"])
	titleZh, _ := skim["title_zh"].(string)
	abstractZh, _ := skim["abstract_zh"].(string)

	// 2a. analysis_reports upsert（paper_id UNIQUE）
	summaryMD := fmt.Sprintf("- 一句话: %s\n- 创新点:\n%s", oneLiner, bulletList(innovations))
	keyInsights := mustJSON(map[string]any{
		"skim_innovations": innovations,
		"skim_one_liner":   oneLiner,
	})
	var existingReport string
	err = tx.QueryRow(`SELECT id FROM analysis_reports WHERE paper_id=$1`, paperID).Scan(&existingReport)
	switch {
	case err == sql.ErrNoRows:
		if _, err = tx.Exec(
			`INSERT INTO analysis_reports (id, paper_id, summary_md, key_insights, skim_score, created_at, updated_at)
			 VALUES ($1, $2, $3, $4, $5, $6, $7)`,
			newCoreID(), paperID, summaryMD, keyInsights, relevanceScore, nowParam(), nowParam(),
		); err != nil {
			return "", fmt.Errorf("analysis_reports insert: %w", err)
		}
	case err != nil:
		return "", err
	default:
		if _, err = tx.Exec(
			`UPDATE analysis_reports SET summary_md=$1, key_insights=$2, skim_score=$3, updated_at=$4
			 WHERE paper_id=$5`,
			summaryMD, keyInsights, relevanceScore, paperID,
		); err != nil {
			return "", fmt.Errorf("analysis_reports update: %w", err)
		}
	}

	// 2b. papers：read_status='skimmed' + metadata 列合并（keywords/title_zh/abstract_zh）
	// （注意：SQLAlchemy 属性名 metadata_json，实际列名是 "metadata"——保留字转义）
	var metadataJSON sql.NullString
	if err = tx.QueryRow(`SELECT metadata FROM papers WHERE id=$1`, paperID).Scan(&metadataJSON); err != nil {
		return "", fmt.Errorf("paper %s 不存在: %w", paperID, err)
	}
	metadata := map[string]any{}
	if metadataJSON.Valid && metadataJSON.String != "" {
		_ = json.Unmarshal([]byte(metadataJSON.String), &metadata)
	}
	if len(keywords) > 0 {
		metadata["keywords"] = keywords
	}
	if titleZh != "" {
		metadata["title_zh"] = titleZh
	}
	if abstractZh != "" {
		metadata["abstract_zh"] = abstractZh
	}
	if _, err = tx.Exec(
		`UPDATE papers SET read_status='skimmed', metadata=$1 WHERE id=$2`,
		mustJSON(metadata), paperID,
	); err != nil {
		return "", fmt.Errorf("papers update: %w", err)
	}

	// 2c. prompt_traces 插入（成本观测，随领域变化同事务）
	if trace != nil {
		if _, err = tx.Exec(
			`INSERT INTO prompt_traces (id, paper_id, stage, provider, model, prompt_digest,
			 input_tokens, output_tokens, input_cost_usd, output_cost_usd, total_cost_usd, created_at)
			 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)`,
			newCoreID(), nullIfEmpty(stringOr(trace["paper_id"])),
			stringOr(trace["stage"]), stringOr(trace["provider"]), stringOr(trace["model"]),
			stringOr(trace["prompt_digest"]),
			jsonInt(trace["input_tokens"]), jsonInt(trace["output_tokens"]),
			jsonFloat(trace["input_cost_usd"]), jsonFloat(trace["output_cost_usd"]),
			jsonFloat(trace["total_cost_usd"]), nowParam(),
		); err != nil {
			return "", fmt.Errorf("prompt_traces insert: %w", err)
		}
	}

	// ---- 3. Task/Attempt 终态（与领域变化同一事务）----
	if err = finalizeTask(tx, taskID, result); err != nil {
		return "", err
	}

	if err = tx.Commit(); err != nil {
		return "", err
	}
	return "succeeded", nil
}

// applyDeepReadResult：analysis_reports.deep_dive_md + read_status 升级（只升不降）
// + prompt_traces——与 Python domain_apply 语义对齐；proposal 模式下 inline
// claim 抽取由独立 extract_claims 任务承载。
func (s *CoreStore) applyDeepReadResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	paperID, _ := proposal["paper_id"].(string)
	deep, _ := proposal["deep"].(map[string]any)
	trace, _ := proposal["trace"].(map[string]any)
	if paperID == "" || deep == nil {
		return "", fmt.Errorf("proposal 缺少 paper_id/deep")
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	methodSummary, _ := deep["method_summary"].(string)
	experimentsSummary, _ := deep["experiments_summary"].(string)
	ablationSummary, _ := deep["ablation_summary"].(string)
	reviewerRisks := jsonStringList(deep["reviewer_risks"])
	deepMD := fmt.Sprintf(
		"## Method\n%s\n\n## Experiments\n%s\n\n## Ablation\n%s\n\n## Reviewer Risks\n%s",
		methodSummary, experimentsSummary, ablationSummary, bulletList(reviewerRisks),
	)

	var existingReport string
	err = tx.QueryRow(`SELECT id FROM analysis_reports WHERE paper_id=$1`, paperID).Scan(&existingReport)
	switch {
	case err == sql.ErrNoRows:
		if _, err = tx.Exec(
			`INSERT INTO analysis_reports (id, paper_id, deep_dive_md, key_insights, created_at, updated_at)
			 VALUES ($1, $2, $3, '{}', $4, $5)`,
			newCoreID(), paperID, deepMD, nowParam(), nowParam(),
		); err != nil {
			return "", fmt.Errorf("analysis_reports insert: %w", err)
		}
	case err != nil:
		return "", err
	default:
		// key_insights 保留既有 skim 内容（Python 语义：合并而非覆盖）
		if _, err = tx.Exec(
			`UPDATE analysis_reports SET deep_dive_md=$1, updated_at=$2 WHERE paper_id=$3`,
			deepMD, nowParam(), paperID,
		); err != nil {
			return "", fmt.Errorf("analysis_reports update: %w", err)
		}
	}

	// read_status 只升不降（unread→skimmed→deep_read）
	if _, err = tx.Exec(
		`UPDATE papers SET read_status='deep_read'
		 WHERE id=$1 AND (read_status='unread' OR read_status='skimmed')`,
		paperID,
	); err != nil {
		return "", fmt.Errorf("papers read_status: %w", err)
	}

	if trace != nil {
		if _, err = tx.Exec(
			`INSERT INTO prompt_traces (id, paper_id, stage, provider, model, prompt_digest,
			 input_tokens, output_tokens, input_cost_usd, output_cost_usd, total_cost_usd, created_at)
			 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)`,
			newCoreID(), nullIfEmpty(stringOr(trace["paper_id"])),
			stringOr(trace["stage"]), stringOr(trace["provider"]), stringOr(trace["model"]),
			stringOr(trace["prompt_digest"]),
			jsonInt(trace["input_tokens"]), jsonInt(trace["output_tokens"]),
			jsonFloat(trace["input_cost_usd"]), jsonFloat(trace["output_cost_usd"]),
			jsonFloat(trace["total_cost_usd"]), nowParam(),
		); err != nil {
			return "", fmt.Errorf("prompt_traces insert: %w", err)
		}
	}

	if err = finalizeTask(tx, taskID, result); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return "succeeded", nil
}

// applyEmbedResult：papers.embedding_vec 写入（JSON 数组形态，SQLite fallback）+ 终态
func (s *CoreStore) applyEmbedResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	paperID, _ := proposal["paper_id"].(string)
	vector, _ := proposal["vector"].([]any)
	if paperID == "" || vector == nil {
		return "", fmt.Errorf("proposal 缺少 paper_id/vector")
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	if _, err = tx.Exec(
		`UPDATE papers SET embedding_vec=$1, updated_at=$2 WHERE id=$3`,
		mustJSON(vector), nowParam(), paperID,
	); err != nil {
		return "", fmt.Errorf("papers embedding: %w", err)
	}

	if err = finalizeTask(tx, taskID, result); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return "succeeded", nil
}

// applyIngestPapersResult：批量入库（A 档升级）——papers upsert（arxiv_id 幂等 +
// skim 保护合并）+ topic 解析/自动创建 + paper_topics 关联 + collection_actions，
// 单事务。与 domain_apply.apply_ingest_papers_proposal 语义逐字段对齐。
// 差异（有意修正）：topic_subscriptions 已存在时不改写 enabled（旧 Python 路径
// 会把用户已启用订阅禁掉）。
func (s *CoreStore) applyIngestPapersResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	query, _ := proposal["query"].(string)
	items, _ := proposal["papers"].([]any)
	// 空 papers = 合法 no-op（重复摄入全部命中已存在）——成功 total=0
	topicID, _ := proposal["topic_id"].(string)
	topicName, _ := proposal["topic_name"].(string)
	actionType, _ := proposal["action_type"].(string)
	if actionType == "" {
		actionType = "manual_collect"
	}
	actionTitle, _ := proposal["action_title"].(string)
	if actionTitle == "" && len(query) > 80 {
		actionTitle = query[:80]
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	// topic 解析：显式 topic_id > topic_name 自动创建（不存在时 enabled=false）
	if topicID == "" && strings.TrimSpace(topicName) != "" {
		err = tx.QueryRow(`SELECT id FROM topic_subscriptions WHERE name=$1`, topicName).Scan(&topicID)
		if err == sql.ErrNoRows {
			newID := newCoreID()
			if _, err = tx.Exec(
				`INSERT INTO topic_subscriptions (id, name, query, enabled, created_at, updated_at)
				 VALUES ($1, $2, $3, 0, NOW(), NOW())`,
				newID, topicName, topicName,
			); err != nil {
				return "", fmt.Errorf("topic_subscriptions insert: %w", err)
			}
			topicID = newID
		} else if err != nil {
			return "", err
		}
	}

	// 逐篇 papers upsert（幂等）+ paper_topics 关联
	insertedIDs := []string{}
	for _, itemAny := range items {
		item, ok := itemAny.(map[string]any)
		if !ok {
			continue
		}
		arxivID, _ := item["arxiv_id"].(string)
		if arxivID == "" {
			continue
		}
		title, _ := item["title"].(string)
		abstract, _ := item["abstract"].(string)
		pubDate, _ := item["publication_date"].(string)
		source, _ := item["source"].(string)
		if source == "" {
			source = "arxiv"
		}
		metaJSON := mergeMetadataFromItem(item["metadata"])

		paperID := newCoreID()
		var existingID string
		err = tx.QueryRow(`SELECT id FROM papers WHERE arxiv_id=$1`, arxivID).Scan(&existingID)
		if err == nil {
			paperID = existingID
			if metaJSON != "" {
				if _, err = tx.Exec(
					`UPDATE papers SET title=$1, abstract=$2, metadata=$3, updated_at=NOW() WHERE id=$4`,
					title, abstract, metaJSON, paperID,
				); err != nil {
					return "", err
				}
			} else if _, err = tx.Exec(
				`UPDATE papers SET title=$1, abstract=$2, updated_at=NOW() WHERE id=$3`,
				title, abstract, paperID,
			); err != nil {
				return "", err
			}
		} else if err == sql.ErrNoRows {
			if _, err = tx.Exec(
				`INSERT INTO papers (id, title, arxiv_id, abstract, read_status, metadata, source, source_id, publication_date, created_at, updated_at)
				 VALUES ($1, $2, $3, $4, 'unread', $5, $6, $7, $8, NOW(), NOW())`,
				paperID, title, arxivID, abstract, metaJSON, source, arxivID, pubDate,
			); err != nil {
				return "", fmt.Errorf("papers insert: %w", err)
			}
		} else {
			return "", err
		}
		insertedIDs = append(insertedIDs, paperID)

		if topicID != "" {
			var linkID string
			err = tx.QueryRow(
				`SELECT id FROM paper_topics WHERE paper_id=$1 AND topic_id=$2`, paperID, topicID,
			).Scan(&linkID)
			if err == sql.ErrNoRows {
				if _, err = tx.Exec(
					`INSERT INTO paper_topics (id, paper_id, topic_id) VALUES ($1, $2, $3)`,
					newCoreID(), paperID, topicID,
				); err != nil {
					return "", fmt.Errorf("paper_topics insert: %w", err)
				}
			} else if err != nil {
				return "", err
			}
		}
	}

	// collection_actions + action_papers
	actionID := newCoreID()
	if _, err = tx.Exec(
		`INSERT INTO collection_actions (id, action_type, title, query, topic_id, paper_count, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, NOW())`,
		actionID, actionType, actionTitle, query, nullIfEmpty(topicID), len(insertedIDs),
	); err != nil {
		return "", fmt.Errorf("collection_actions insert: %w", err)
	}
	for _, pid := range insertedIDs {
		if _, err = tx.Exec(
			`INSERT INTO action_papers (id, action_id, paper_id) VALUES ($1, $2, $3)`,
			newCoreID(), actionID, pid,
		); err != nil {
			return "", fmt.Errorf("action_papers insert: %w", err)
		}
	}

	if err = finalizeTaskWithResult(tx, taskID, map[string]any{
		"total": len(insertedIDs), "inserted_ids": insertedIDs, "topic_id": topicID,
	}); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return fmt.Sprintf("succeeded (papers=%d)", len(insertedIDs)), nil
}

// mergeMetadataFromItem：paper item 携带的 metadata 序列化（空则返回空串跳过写入）
func mergeMetadataFromItem(incoming any) string {
	m, ok := incoming.(map[string]any)
	if !ok || len(m) == 0 {
		return ""
	}
	return mustJSON(m)
}

// applySaveGeneratedContentResult：generated_contents 插入（A 档升级）——
// topic_wiki / daily_brief 共用；result_ref 携带 content_id（前端历史记录契约）。
func (s *CoreStore) applySaveGeneratedContentResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	contentType, _ := proposal["content_type"].(string)
	title, _ := proposal["title"].(string)
	markdown, _ := proposal["markdown"].(string)
	keyword := nullIfEmpty(stringOr(proposal["keyword"]))
	paperID := nullIfEmpty(stringOr(proposal["paper_id"]))
	metaJSON := "{}"
	if m, ok := proposal["metadata_json"].(map[string]any); ok && len(m) > 0 {
		metaJSON = mustJSON(m)
	}
	if contentType == "" || title == "" {
		return "", fmt.Errorf("proposal 缺少 content_type/title")
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	contentID := newCoreID()
	if _, err = tx.Exec(
		`INSERT INTO generated_contents (id, content_type, title, keyword, paper_id, markdown, metadata_json, created_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
		contentID, contentType, title, keyword, paperID, markdown, metaJSON, nowParam(),
	); err != nil {
		return "", fmt.Errorf("generated_contents insert: %w", err)
	}

	// result_ref：content_id 权威 + 保留 handler 顶层字段（email_sent/saved_path
	// 等消费者契约——/tasks/{id}/result）
	ref := map[string]any{"content_id": contentID, "content_type": contentType}
	for k, v := range result {
		if k != "proposal" {
			ref[k] = v
		}
	}
	if err = finalizeTaskWithResult(tx, taskID, ref); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return "succeeded", nil
}

// upsertPaperWithMeta：papers upsert（PaperCreate 形态 dict）——citation_edges /
// reference_import 共用；返回 paper_id。
func upsertPaperWithMeta(tx *sql.Tx, paper map[string]any) (string, error) {
	arxivID, _ := paper["arxiv_id"].(string)
	title, _ := paper["title"].(string)
	abstract, _ := paper["abstract"].(string)
	if arxivID == "" {
		// SS-only 论文：标题归一化 id（与 Python _title_to_id 语义一致，此处由
		// proposal 已算好传入 arxiv_id=ss-...；空值兜底）
		arxivID = "ss-" + fmt.Sprintf("%x", sha256Hex(title))[:40]
	}
	metaJSON := "{}"
	if m, ok := paper["metadata"].(map[string]any); ok && len(m) > 0 {
		metaJSON = mustJSON(m)
	}
	pubDate, _ := paper["publication_date"].(string)
	source, _ := paper["source"].(string)
	if source == "" {
		source = "arxiv"
	}
	paperID := newCoreID()
	var existingID string
	err := tx.QueryRow(`SELECT id FROM papers WHERE arxiv_id=$1`, arxivID).Scan(&existingID)
	if err == nil {
		paperID = existingID
		if _, err = tx.Exec(
			`UPDATE papers SET title=$1, abstract=$2, metadata=$3, updated_at=NOW() WHERE id=$4`,
			title, abstract, metaJSON, paperID,
		); err != nil {
			return "", err
		}
	} else if err == sql.ErrNoRows {
		if _, err = tx.Exec(
			`INSERT INTO papers (id, title, arxiv_id, abstract, read_status, metadata, source, source_id, publication_date, created_at, updated_at)
			 VALUES ($1, $2, $3, $4, 'unread', $5, $6, $7, $8, NOW(), NOW())`,
			paperID, title, arxivID, abstract, metaJSON, source, arxivID, pubDate,
		); err != nil {
			return "", fmt.Errorf("papers insert: %w", err)
		}
	} else {
		return "", err
	}
	return paperID, nil
}

// applyCitationEdgesResult：引用边批量入库（A 档）——papers upsert（双侧，
// arxiv_id 幂等）+ citation 边 upsert（幂等 + context 更新），单事务。
func (s *CoreStore) applyCitationEdgesResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	edges, _ := proposal["edges"].([]any)

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	inserted := 0
	for _, eAny := range edges {
		e, ok := eAny.(map[string]any)
		if !ok {
			continue
		}
		srcPaper, _ := e["source"].(map[string]any)
		dstPaper, _ := e["target"].(map[string]any)
		if srcPaper == nil || dstPaper == nil {
			continue
		}
		srcID, err := upsertPaperWithMeta(tx, srcPaper)
		if err != nil {
			return "", err
		}
		dstID, err := upsertPaperWithMeta(tx, dstPaper)
		if err != nil {
			return "", err
		}
		context, _ := e["context"].(string)
		var existing string
		err = tx.QueryRow(
			`SELECT id FROM citations WHERE source_paper_id=$1 AND target_paper_id=$2`, srcID, dstID,
		).Scan(&existing)
		if err == sql.ErrNoRows {
			if _, err = tx.Exec(
				`INSERT INTO citations (id, source_paper_id, target_paper_id, context, created_at)
				 VALUES ($1, $2, $3, $4, NOW())`,
				newCoreID(), srcID, dstID, nullIfEmpty(context),
			); err != nil {
				return "", fmt.Errorf("citations insert: %w", err)
			}
			inserted++
		} else if err != nil {
			return "", err
		} else if context != "" {
			if _, err = tx.Exec(`UPDATE citations SET context=$1 WHERE id=$2`, context, existing); err != nil {
				return "", err
			}
		}
	}

	if err = finalizeTaskWithResult(tx, taskID, map[string]any{"edges_inserted": inserted}); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return fmt.Sprintf("succeeded (edges=%d)", inserted), nil
}

// applyFigureAnalysesResult：image_analyses 删重建（A 档；幂等语义与 Python
// _save_analyses 一致——图片文件已由 handler 落盘，路径随 proposal 传入）。
func (s *CoreStore) applyFigureAnalysesResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	paperID, _ := proposal["paper_id"].(string)
	analyses, _ := proposal["analyses"].([]any)
	if paperID == "" {
		return "", fmt.Errorf("proposal 缺少 paper_id")
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	if _, err = tx.Exec(`DELETE FROM image_analyses WHERE paper_id=$1`, paperID); err != nil {
		return "", err
	}
	for _, aAny := range analyses {
		a, ok := aAny.(map[string]any)
		if !ok {
			continue
		}
		pageNumber := int(jsonFloat(a["page_number"]).(float64))
		imageIndex := int(jsonFloat(a["image_index"]).(float64))
		imageType, _ := a["image_type"].(string)
		caption := nullIfEmpty(stringOr(a["caption"]))
		description, _ := a["description"].(string)
		imagePath := nullIfEmpty(stringOr(a["image_path"]))
		bbox := "{}"
		if b, ok := a["bbox_json"].(map[string]any); ok && len(b) > 0 {
			bbox = mustJSON(b)
		}
		if _, err = tx.Exec(
			`INSERT INTO image_analyses (id, paper_id, page_number, image_index, image_type, caption, description, image_path, bbox_json, created_at)
			 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())`,
			newCoreID(), paperID, pageNumber, imageIndex, imageType, caption, description, imagePath, bbox,
		); err != nil {
			return "", fmt.Errorf("image_analyses insert: %w", err)
		}
	}

	if err = finalizeTaskWithResult(tx, taskID, map[string]any{"count": len(analyses)}); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return fmt.Sprintf("succeeded (figures=%d)", len(analyses)), nil
}

// applyPaperTranslationResult：paper_translations upsert（A 档；paper_id+
// target_lang+mode 唯一——存在则更新 segments/bilingual_pdf_path）。
func (s *CoreStore) applyPaperTranslationResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	paperID, _ := proposal["paper_id"].(string)
	targetLang, _ := proposal["target_lang"].(string)
	mode, _ := proposal["mode"].(string)
	if paperID == "" || targetLang == "" || mode == "" {
		return "", fmt.Errorf("proposal 缺少 paper_id/target_lang/mode")
	}
	segments := "{}"
	if segs, ok := proposal["segments"].([]any); ok {
		segments = mustJSON(segs)
	}
	bilingualPath := nullIfEmpty(stringOr(proposal["bilingual_pdf_path"]))

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	var existing string
	err = tx.QueryRow(
		`SELECT id FROM paper_translations WHERE paper_id=$1 AND target_lang=$2 AND mode=$3`,
		paperID, targetLang, mode,
	).Scan(&existing)
	switch {
	case err == sql.ErrNoRows:
		if _, err = tx.Exec(
			`INSERT INTO paper_translations (id, paper_id, target_lang, mode, segments, bilingual_pdf_path, created_at, updated_at)
			 VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())`,
			newCoreID(), paperID, targetLang, mode, segments, bilingualPath,
		); err != nil {
			return "", fmt.Errorf("paper_translations insert: %w", err)
		}
	case err != nil:
		return "", err
	default:
		if _, err = tx.Exec(
			`UPDATE paper_translations SET segments=$1, bilingual_pdf_path=$2, updated_at=NOW() WHERE id=$3`,
			segments, bilingualPath, existing,
		); err != nil {
			return "", err
		}
	}

	if err = finalizeTaskWithResult(tx, taskID, map[string]any{
		"paper_id": paperID, "target_lang": targetLang, "mode": mode,
	}); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return "succeeded", nil
}

// applyReferenceImportResult：参考文献导入（A 档）——papers upsert（完整元数据）
// + topic 关联 + citation 边（source_paper 固定一侧）+ collection action，单事务。
func (s *CoreStore) applyReferenceImportResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	sourcePaperID, _ := proposal["source_paper_id"].(string)
	sourceTitle, _ := proposal["source_paper_title"].(string)
	items, _ := proposal["papers"].([]any)
	if sourcePaperID == "" || len(items) == 0 {
		return "", fmt.Errorf("proposal 缺少 source_paper_id/papers")
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	insertedIDs := []string{}
	for _, itemAny := range items {
		item, ok := itemAny.(map[string]any)
		if !ok {
			continue
		}
		paper, _ := item["paper"].(map[string]any)
		if paper == nil {
			continue
		}
		paperID, err := upsertPaperWithMeta(tx, paper)
		if err != nil {
			return "", err
		}
		insertedIDs = append(insertedIDs, paperID)

		if topics, ok := item["topics"].([]any); ok {
			for _, tAny := range topics {
				tid, _ := tAny.(string)
				if tid == "" {
					continue
				}
				var linkID string
				err = tx.QueryRow(
					`SELECT id FROM paper_topics WHERE paper_id=$1 AND topic_id=$2`, paperID, tid,
				).Scan(&linkID)
				if err == sql.ErrNoRows {
					if _, err = tx.Exec(
						`INSERT INTO paper_topics (id, paper_id, topic_id) VALUES ($1, $2, $3)`,
						newCoreID(), paperID, tid,
					); err != nil {
						return "", fmt.Errorf("paper_topics insert: %w", err)
					}
				} else if err != nil {
					return "", err
				}
			}
		}

		direction, _ := item["direction"].(string)
		if direction == "" {
			direction = "reference"
		}
		context := "reference"
		var srcID, dstID string
		if direction == "reference" {
			srcID, dstID = sourcePaperID, paperID
		} else {
			srcID, dstID = paperID, sourcePaperID
			context = "citation"
		}
		var edgeExists string
		err = tx.QueryRow(
			`SELECT id FROM citations WHERE source_paper_id=$1 AND target_paper_id=$2`, srcID, dstID,
		).Scan(&edgeExists)
		if err == sql.ErrNoRows {
			if _, err = tx.Exec(
				`INSERT INTO citations (id, source_paper_id, target_paper_id, context, created_at)
				 VALUES ($1, $2, $3, $4, NOW())`,
				newCoreID(), srcID, dstID, context,
			); err != nil {
				return "", fmt.Errorf("citations insert: %w", err)
			}
		} else if err != nil {
			return "", err
		}
	}

	actionID := newCoreID()
	if _, err = tx.Exec(
		`INSERT INTO collection_actions (id, action_type, title, query, paper_count, created_at)
		 VALUES ($1, 'reference_import', $2, $3, $4, NOW())`,
		actionID, ("参考文献导入：" + sourceTitle)[:min(len("参考文献导入："+sourceTitle), 512)], sourcePaperID, len(insertedIDs),
	); err != nil {
		return "", fmt.Errorf("collection_actions insert: %w", err)
	}
	for _, pid := range insertedIDs {
		if _, err = tx.Exec(
			`INSERT INTO action_papers (id, action_id, paper_id) VALUES ($1, $2, $3)`,
			newCoreID(), actionID, pid,
		); err != nil {
			return "", fmt.Errorf("action_papers insert: %w", err)
		}
	}

	if err = finalizeTaskWithResult(tx, taskID, map[string]any{
		"inserted_ids": insertedIDs, "total": len(insertedIDs),
	}); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return fmt.Sprintf("succeeded (papers=%d)", len(insertedIDs)), nil
}

// FailTask 失败上报（core 表；重试/dead_letter 语义与 Python durable 一致）
func (s *CoreStore) FailTask(taskID, executorID, leaseToken, errorClass, message string) (string, error) {
	var status string
	var attemptCount, maxAttempts int
	var leaseTokenDB sql.NullString
	err := s.DB.QueryRow(
		`SELECT status, attempt_count, max_attempts, lease_token FROM core_tasks WHERE id=$1`,
		taskID,
	).Scan(&status, &attemptCount, &maxAttempts, &leaseTokenDB)
	if err != nil {
		return "", err
	}
	if (status != "leased" && status != "cancelling") || !leaseTokenDB.Valid || leaseTokenDB.String != leaseToken {
		return "", fmt.Errorf("task %s fail 被拒绝（状态 %s / lease 不匹配）", taskID, status)
	}
	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()
	newStatus := "queued"
	if attemptCount >= maxAttempts {
		newStatus = "dead_letter"
	}
	if status == "cancelling" {
		newStatus = "cancelled" // 协作取消：不再重新入队
	}
	now := nowParam()
	if _, err = tx.Exec(
		`UPDATE core_tasks SET status=$1, lease_token=NULL, lease_expires_at=NULL, last_error=$2 WHERE id=$3`,
		newStatus, errorClass+": "+message, taskID,
	); err != nil {
		return "", err
	}
	if _, err = tx.Exec(
		`UPDATE core_attempts SET status='failed', error_class=$1, finished_at=$2
		 WHERE task_id=$3 AND fencing_token=$4 AND status='running'`,
		errorClass, now, taskID, attemptCount,
	); err != nil {
		return "", err
	}
	// Job 收敛：全部终态 → failed/partially（单任务切片：失败 → failed）
	if newStatus == "dead_letter" {
		if _, err = tx.Exec(
			`UPDATE core_jobs SET status='failed', finished_at=$1 WHERE id=$2 AND status='running'`,
			now, jobIDOf(tx, taskID),
		); err != nil {
			return "", err
		}
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return newStatus, nil
}

// ReclaimExpired 回收过期 lease（Reconciler 权威逻辑，Go 侧）
func (s *CoreStore) ReclaimExpired(backoffS int) (map[string]string, error) {
	// 第四轮 P0-3：datetime('now', ?) 是 SQLite-only——用跨方言字符串比较
	// （lease_expires_at/nowParam 统一 UTC 字符串格式）
	cutoff := time.Now().UTC().Add(-time.Duration(backoffS) * time.Second).Format("2006-01-02 15:04:05.000000")
	rows, err := s.DB.Query(
		`SELECT id, attempt_count, max_attempts, status FROM core_tasks
		 WHERE status IN ('leased','cancelling') AND lease_expires_at < $1`,
		cutoff,
	)
	if err != nil {
		return nil, err
	}
	type expired struct {
		id, status   string
		attemptCount int
		maxAttempts  int
	}
	var list []expired
	for rows.Next() {
		var e expired
		if err = rows.Scan(&e.id, &e.attemptCount, &e.maxAttempts, &e.status); err != nil {
			rows.Close()
			return nil, err
		}
		list = append(list, e)
	}
	rows.Close()

	out := map[string]string{}
	for _, e := range list {
		newStatus := "queued"
		if e.attemptCount >= e.maxAttempts {
			newStatus = "dead_letter"
		}
		finalStatus := newStatus
		if e.status == "cancelling" {
			finalStatus = "cancelled" // 取消中的过期 lease → cancelled（不重排）
		}
		if _, err = s.DB.Exec(
			`UPDATE core_tasks SET status=$1, lease_token=NULL, lease_expires_at=NULL WHERE id=$2`,
			finalStatus, e.id,
		); err != nil {
			return nil, err
		}
		if _, err = s.DB.Exec(
			`UPDATE core_attempts SET status='failed', error_class='lease_expired', finished_at=$1
			 WHERE task_id=$2 AND fencing_token=$3 AND status='running'`,
			nowParam(), e.id, e.attemptCount,
		); err != nil {
			return nil, err
		}
		out[e.id] = map[bool]string{true: "requeued", false: "dead_letter"}[finalStatus == "queued"]
	}
	return out, nil
}

// applyUpsertPaperResult：papers 行 upsert + source_versions v1 + outbox（单事务）
func (s *CoreStore) applyUpsertPaperResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	arxivID, _ := proposal["arxiv_id"].(string)
	title, _ := proposal["title"].(string)
	abstract, _ := proposal["abstract"].(string)
	if arxivID == "" {
		return "", fmt.Errorf("proposal 缺少 arxiv_id")
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	attemptCount, err := fencingGuard(tx, taskID, executorID, leaseToken)
	if err != nil {
		return "", err
	}

	// papers upsert（幂等：arxiv_id 唯一；metadata 合并——保留既有 skim 派生字段）
	paperID := newCoreID()
	var existingID string
	err = tx.QueryRow(`SELECT id FROM papers WHERE arxiv_id=$1`, arxivID).Scan(&existingID)
	if err == nil {
		paperID = existingID
		if metaJSON := mergeMetadata(tx, paperID, proposal["metadata"]); metaJSON != "" {
			if _, err = tx.Exec(
				`UPDATE papers SET title=$1, abstract=$2, metadata=$3, updated_at=NOW() WHERE id=$4`,
				title, abstract, metaJSON, paperID,
			); err != nil {
				return "", err
			}
		} else if _, err = tx.Exec(
			`UPDATE papers SET title=$1, abstract=$2, updated_at=NOW() WHERE id=$3`,
			title, abstract, paperID,
		); err != nil {
			return "", err
		}
	} else if err == sql.ErrNoRows {
		metaJSON := "{}"
		if m, ok := proposal["metadata"].(map[string]any); ok && len(m) > 0 {
			metaJSON = mustJSON(m)
		}
		if _, err = tx.Exec(
			`INSERT INTO papers (id, title, arxiv_id, abstract, read_status, metadata, created_at, updated_at)
			 VALUES ($1, $2, $3, $4, 'unread', $5, NOW(), NOW())`,
			paperID, title, arxivID, abstract, metaJSON,
		); err != nil {
			return "", fmt.Errorf("papers insert: %w", err)
		}
	} else {
		return "", err
	}

	// SourceVersion v1
	var svID string
	err = tx.QueryRow(
		`SELECT id FROM source_versions WHERE paper_id=$1 AND is_current=1`, paperID,
	).Scan(&svID)
	if err == sql.ErrNoRows {
		svID = newCoreID()
		identityJSON := fmt.Sprintf(`{"abstract":%q,"arxiv_id":%q,"title":%q}`, abstract, arxivID, title)
		if _, err = tx.Exec(
			`INSERT INTO source_versions (id, paper_id, version_label, content_hash, detected_by, is_current, created_at)
			 VALUES ($1, $2, 1, $3, 'ingest', true, NOW())`,
			svID, paperID, sha256Hex(identityJSON),
		); err != nil {
			return "", err
		}
		if _, err = tx.Exec(
			`INSERT INTO research_events (id, type, aggregate_type, aggregate_id, payload, occurred_at)
			 VALUES ($1, 'source_version_detected', 'source_version', $2, $3, NOW())`,
			newCoreID(), svID, mustJSON(map[string]any{"paper_id": paperID}),
		); err != nil {
			return "", err
		}
	} else if err != nil {
		return "", err
	}

	if err = finalizeTaskWithResult(tx, taskID, map[string]any{
		"paper_id": paperID, "arxiv_id": arxivID,
	}); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	_ = attemptCount
	return "succeeded", nil
}

// applyDownloadSourceResult：PDF 下载 + papers.pdf_path 更新（单事务终态）
func (s *CoreStore) applyDownloadSourceResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	arxivID, _ := proposal["arxiv_id"].(string)
	// pdf_path：Python handler 真实下载后的本地路径；pdf_url：Go executor 的
	// URL 形态（未落盘）。二者都写 papers.pdf_path（path 语义）。
	pdfRef, _ := proposal["pdf_path"].(string)
	if pdfRef == "" {
		pdfRef, _ = proposal["pdf_url"].(string)
	}
	if arxivID == "" || pdfRef == "" {
		return "", fmt.Errorf("proposal 缺少 arxiv_id/pdf_path")
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	if _, err = tx.Exec(
		`UPDATE papers SET pdf_path=$1, updated_at=NOW() WHERE arxiv_id=$2`,
		pdfRef, arxivID,
	); err != nil {
		return "", err
	}

	if err = finalizeTask(tx, taskID, result); err != nil {
		return "", err
	}
	if err = tx.Commit(); err != nil {
		return "", err
	}
	return "succeeded", nil
}

// applyExtractClaimsResult：claims SQL 直写（A 档升级——第三轮 P0-2 选 a 迁移清单）
//
// 同一事务内：ResearchRun 创建 + SourceVersion 幂等回补 + Claim 创建（papermind
// draft，provenance 硬规则）+ Evidence 创建（quote 幂等 + fingerprint SHA256）
// + research_events outbox（claim_proposed/evidence_extracted）+ prompt_traces
// + Task/Attempt 终态。
func (s *CoreStore) applyExtractClaimsResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	proposal, _ := result["proposal"].(map[string]any)
	if proposal == nil {
		return "", fmt.Errorf("result 缺少 proposal")
	}
	paperID, _ := proposal["paper_id"].(string)
	items, _ := proposal["items"].([]any)
	trace, _ := proposal["trace"].(map[string]any)
	runMeta, _ := proposal["run_meta"].(map[string]any)
	if paperID == "" {
		return "", fmt.Errorf("proposal 缺少 paper_id")
	}

	tx, err := s.DB.Begin()
	if err != nil {
		return "", err
	}
	defer tx.Rollback()

	if _, err := fencingGuard(tx, taskID, executorID, leaseToken); err != nil {
		return "", err
	}

	// ---- ResearchRun ----
	runID := newCoreID()
	modelPolicy := "{}"
	if runMeta != nil {
		if mp, ok := runMeta["model_policy"].(map[string]any); ok {
			modelPolicy = mustJSON(mp)
		}
	}
	if _, err = tx.Exec(
		`INSERT INTO research_runs (id, kind, trigger, paper_ids, model_policy, status, started_at)
		 VALUES ($1, 'claim_extraction', 'api', $2, $3, 'succeeded', $4)`,
		runID, mustJSON([]string{paperID}), modelPolicy, nowParam(),
	); err != nil {
		return "", fmt.Errorf("research_runs insert: %w", err)
	}

	// ---- SourceVersion 幂等回补（get_current → 无则 create v1）----
	svID := ""
	err = tx.QueryRow(
		`SELECT id FROM source_versions WHERE paper_id=$1 AND is_current=1 LIMIT 1`, paperID,
	).Scan(&svID)
	if err == sql.ErrNoRows {
		svID = newCoreID()
		// identity_hash: sha256(json({abstract, arxiv_id, title}, sort_keys))
		var abstract, arxivID, title string
		_ = tx.QueryRow(
			`SELECT abstract, arxiv_id, title FROM papers WHERE id=$1`, paperID,
		).Scan(&abstract, &arxivID, &title)
		identityJSON := mustJSON(map[string]string{
			"abstract": abstract, "arxiv_id": arxivID, "title": title,
		})
		contentHash := sha256Hex(identityJSON)
		// version_label = max+1
		var maxLabel int
		_ = tx.QueryRow(
			`SELECT COALESCE(MAX(version_label), 0) FROM source_versions WHERE paper_id=$1`, paperID,
		).Scan(&maxLabel)
		// 降级旧 current
		if _, err = tx.Exec(
			`UPDATE source_versions SET is_current=0 WHERE paper_id=$1 AND is_current=1`, paperID,
		); err != nil {
			return "", err
		}
		if _, err = tx.Exec(
			`INSERT INTO source_versions (id, paper_id, version_label, content_hash, detected_by, is_current, created_at)
			 VALUES ($1, $2, $3, $4, 'ingest', 1, $5)`,
			svID, paperID, maxLabel+1, contentHash, nowParam(),
		); err != nil {
			return "", fmt.Errorf("source_versions insert: %w", err)
		}
		// outbox: source_version_detected
		if _, err = tx.Exec(
			`INSERT INTO research_events (id, type, aggregate_type, aggregate_id, actor, payload, occurred_at)
			 VALUES ($1, 'source_version_detected', 'source_version', $2, 'system', $3, $4)`,
			newCoreID(), svID, mustJSON(map[string]any{"paper_id": paperID, "version_label": maxLabel + 1}), nowParam(),
		); err != nil {
			return "", err
		}
	} else if err != nil {
		return "", err
	}

	// ---- Claims + Evidence（quote 幂等 + fingerprint SHA256）----
	created := 0
	skipped := 0
	for _, itemAny := range items {
		item, ok := itemAny.(map[string]any)
		if !ok {
			continue
		}
		statement := stringOr(item["statement"])
		if statement == "" {
			continue
		}
		quote := stringOr(item["quote"])
		locator := mustJSON(item["locator"])

		// quote 幂等：同版本+同引用 → 已抽取过
		var evidenceCount int
		_ = tx.QueryRow(
			`SELECT COUNT(*) FROM evidence WHERE source_version_id=$1 AND quote=$2`,
			svID, quote,
		).Scan(&evidenceCount)
		if quote != "" && evidenceCount > 0 {
			skipped++
			continue
		}

		claimID := newCoreID()
		certainty := stringOr(item["certainty"])
		if certainty == "" {
			certainty = "insufficient_evidence" // papermind 默认保守
		}
		statementZh := nullIfEmpty(stringOr(item["statement_zh"]))

		if _, err = tx.Exec(
			`INSERT INTO claims (id, statement, statement_zh, origin, status, certainty, run_id, created_at, updated_at)
			 VALUES ($1, $2, $3, 'papermind', 'draft', $4, $5, $6, $7)`,
			claimID, statement, statementZh, certainty, runID, nowParam(), nowParam(),
		); err != nil {
			return "", fmt.Errorf("claims insert: %w", err)
		}

		// outbox: claim_proposed
		claimPayload := mustJSON(map[string]any{
			"statement": statement, "origin": "papermind", "status": "draft", "certainty": certainty,
		})
		if _, err = tx.Exec(
			`INSERT INTO research_events (id, type, aggregate_type, aggregate_id, actor, run_id, payload, occurred_at)
			 VALUES ($1, 'claim_proposed', 'claim', $2, 'papermind', $3, $4, $5, $6)`,
			newCoreID(), claimID, runID, claimPayload, nowParam(), nowParam(),
		); err != nil {
			return "", err
		}

		// Evidence（quote+locator 存在时创建，fingerprint 去重）
		if quote != "" {
			fingerprint := evidenceFingerprint(claimID, svID, "text_passage", locator, quote)
			evID := newCoreID()
			if _, err = tx.Exec(
				`INSERT INTO evidence (id, claim_id, source_version_id, kind, stance, locator, quote, fingerprint, run_id, created_at)
				 VALUES ($1, $2, $3, 'text_passage', 'supports', $4, $5, $6, $7, $8)`,
				evID, claimID, svID, locator, quote, fingerprint, runID, nowParam(),
			); err != nil {
				return "", fmt.Errorf("evidence insert: %w", err)
			}
			// outbox: evidence_extracted
			evPayload := mustJSON(map[string]any{"claim_id": claimID, "source_version_id": svID, "quote": quote})
			if _, err = tx.Exec(
				`INSERT INTO research_events (id, type, aggregate_type, aggregate_id, actor, run_id, payload, occurred_at)
				 VALUES ($1, 'evidence_extracted', 'evidence', $2, 'system', $3, $4, $5, $6)`,
				newCoreID(), evID, runID, evPayload, nowParam(), nowParam(),
			); err != nil {
				return "", err
			}
		}
		created++
	}

	// ---- prompt_traces ----
	if trace != nil {
		if _, err = tx.Exec(
			`INSERT INTO prompt_traces (id, paper_id, stage, provider, model, prompt_digest,
			 input_tokens, output_tokens, input_cost_usd, output_cost_usd, total_cost_usd, created_at)
			 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)`,
			newCoreID(), nullIfEmpty(stringOr(trace["paper_id"])),
			stringOr(trace["stage"]), stringOr(trace["provider"]), stringOr(trace["model"]),
			stringOr(trace["prompt_digest"]),
			jsonInt(trace["input_tokens"]), jsonInt(trace["output_tokens"]),
			jsonFloat(trace["input_cost_usd"]), jsonFloat(trace["output_cost_usd"]),
			jsonFloat(trace["total_cost_usd"]), nowParam(),
		); err != nil {
			return "", fmt.Errorf("prompt_traces insert: %w", err)
		}
	}

	// ---- 终态 ----
	if err = finalizeTask(tx, taskID, map[string]any{
		"claims_created": created, "claims_skipped": skipped,
	}); err != nil {
		return "", err
	}

	if err = tx.Commit(); err != nil {
		return "", err
	}
	return fmt.Sprintf("succeeded (claims=%d skipped=%d)", created, skipped), nil
}

// evidenceFingerprint：SHA256(claim_id+sv_id+kind+locator+quote, sort_keys)——与 Python 逐字段对齐
func evidenceFingerprint(claimID, sourceVersionID, kind string, locatorJSON string, quote string) string {
	_ = locatorJSON
	raw := fmt.Sprintf(`{"claim_id": %q, "kind": %q, "locator": %s, "quote": %q, "source_version_id": %q}`,
		claimID, kind, locatorJSON, quote, sourceVersionID)
	return sha256Hex(raw)
}

func sha256Hex(s string) string {
	h := sha256.Sum256([]byte(s))
	return hex.EncodeToString(h[:])
}

// JobsList 返回最近的 core Job 列表（观察面合并用）

// HeartbeatTask 续约 Go 权威任务的 lease；返回 (ok, cancelRequested, err)

// sqliteTimePlusFromTask：按任务 timeout_s 续约（needDB 传入以查询）

// CancelJob 取消 Job：queued 直接取消，leased 协作取消

// OwnsJob 报告 job 是否属于 Go 权威

// OwnsTask 报告 task 是否属于 Go 权威（claim/complete 路由用）

// ---------- helpers ----------

// mergeMetadata 读取既有 papers.metadata 并合并 proposal 携带的 metadata
// （skim 的 keywords/title_zh/abstract_zh 不被 ingest 元数据覆盖）。
// 返回合并后的 JSON 串；无新增内容返回空串（调用方跳过 metadata 写入）。
func mergeMetadata(tx *sql.Tx, paperID string, incoming any) string {
	incomingMap, ok := incoming.(map[string]any)
	if !ok || len(incomingMap) == 0 {
		return ""
	}
	var existing sql.NullString
	if err := tx.QueryRow(`SELECT metadata FROM papers WHERE id=$1`, paperID).Scan(&existing); err != nil {
		return ""
	}
	metadata := map[string]any{}
	if existing.Valid && existing.String != "" {
		_ = json.Unmarshal([]byte(existing.String), &metadata)
	}
	for k, v := range incomingMap {
		metadata[k] = v
	}
	return mustJSON(metadata)
}

func jobIDOf(tx *sql.Tx, taskID string) string {
	var jobID string
	_ = tx.QueryRow(`SELECT job_id FROM core_tasks WHERE id=$1`, taskID).Scan(&jobID)
	return jobID
}

// finalizeTaskWithResult：终态 + result_ref
func finalizeTaskWithResult(tx *sql.Tx, taskID string, result map[string]any) error {
	now := nowParam()
	if _, err := tx.Exec(
		`UPDATE core_tasks SET status='succeeded', lease_token=NULL, lease_expires_at=NULL,
		 result_ref=$1 WHERE id=?`,
		mustJSON(result), taskID,
	); err != nil {
		return err
	}
	var attemptCount int
	if err := tx.QueryRow(`SELECT attempt_count FROM core_tasks WHERE id=$1`, taskID).Scan(&attemptCount); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`UPDATE core_attempts SET status='succeeded', finished_at=$1
		 WHERE task_id=? AND fencing_token=? AND status='running'`,
		now, taskID, attemptCount,
	); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`UPDATE core_jobs SET status='succeeded', finished_at=$1 WHERE id=? AND status='running'`,
		now, jobIDOf(tx, taskID),
	); err != nil {
		return err
	}
	// Job 收敛（第四轮 P1）：cancelling Job 的 Task 全部终态后 → cancelled
	// （协作取消链路的最后一环——此前 Job 永远停在 cancelling）
	if _, err := tx.Exec(
		`UPDATE core_jobs SET status='cancelled', finished_at=COALESCE(finished_at, $1)
		 WHERE status='cancelling'
		   AND id=(SELECT job_id FROM core_tasks WHERE id=$2)
		   AND NOT EXISTS (SELECT 1 FROM core_tasks WHERE job_id=(SELECT job_id FROM core_tasks WHERE id=$3) AND status IN ('leased','cancelling'))`,
		now, taskID, taskID,
	); err != nil {
		return err
	}
	return nil
}
