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
)

// ApplyResult 按 capability 分派的 apply-result 入口（单事务）。
func (s *CoreStore) ApplyResult(taskID, executorID, leaseToken string, result map[string]any) (string, error) {
	var capability string
	err := s.DB.QueryRow(`SELECT capability FROM core_tasks WHERE id=?`, taskID).Scan(&capability)
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
	default:
		return "", fmt.Errorf("capability %s 未实现 Go apply-result（迁移清单中）", capability)
	}
}

// fencingGuard 在事务内校验 lease 持有者 + attempt 匹配；返回 attempt fencing token。
func fencingGuard(tx *sql.Tx, taskID, executorID, leaseToken string) (int, error) {
	var status string
	var attemptCount int
	var leaseTokenDB sql.NullString
	err := tx.QueryRow(
		`SELECT status, attempt_count, lease_token FROM core_tasks WHERE id=?`,
		taskID,
	).Scan(&status, &attemptCount, &leaseTokenDB)
	if err == sql.ErrNoRows {
		return 0, fmt.Errorf("task %s not found", taskID)
	}
	if err != nil {
		return 0, err
	}
	if status != "leased" {
		return 0, fmt.Errorf("task %s 状态 %s 不可提交", taskID, status)
	}
	if !leaseTokenDB.Valid || leaseTokenDB.String != leaseToken {
		return 0, fmt.Errorf("task %s lease token 不匹配（迟到写入被拒绝）", taskID)
	}
	var attemptExecutor string
	err = tx.QueryRow(
		`SELECT executor_id FROM core_attempts
		 WHERE task_id=? AND fencing_token=? AND status='running'`,
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
	if _, err := tx.Exec(
		`UPDATE core_tasks SET status='succeeded', lease_token=NULL, lease_expires_at=NULL,
		 result_ref=? WHERE id=?`,
		mustJSON(result), taskID,
	); err != nil {
		return err
	}
	var attemptCount int
	if err := tx.QueryRow(`SELECT attempt_count FROM core_tasks WHERE id=?`, taskID).Scan(&attemptCount); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`UPDATE core_attempts SET status='succeeded', finished_at=?
		 WHERE task_id=? AND fencing_token=? AND status='running'`,
		now, taskID, attemptCount,
	); err != nil {
		return err
	}
	if _, err := tx.Exec(
		`UPDATE core_jobs SET status='succeeded', finished_at=? WHERE id=? AND status='running'`,
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
	err = tx.QueryRow(`SELECT id FROM analysis_reports WHERE paper_id=?`, paperID).Scan(&existingReport)
	switch {
	case err == sql.ErrNoRows:
		if _, err = tx.Exec(
			`INSERT INTO analysis_reports (id, paper_id, summary_md, key_insights, skim_score, created_at, updated_at)
			 VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))`,
			newCoreID(), paperID, summaryMD, keyInsights, relevanceScore,
		); err != nil {
			return "", fmt.Errorf("analysis_reports insert: %w", err)
		}
	case err != nil:
		return "", err
	default:
		if _, err = tx.Exec(
			`UPDATE analysis_reports SET summary_md=?, key_insights=?, skim_score=?, updated_at=$1
			 WHERE paper_id=?`,
			summaryMD, keyInsights, relevanceScore, paperID,
		); err != nil {
			return "", fmt.Errorf("analysis_reports update: %w", err)
		}
	}

	// 2b. papers：read_status='skimmed' + metadata 列合并（keywords/title_zh/abstract_zh）
	// （注意：SQLAlchemy 属性名 metadata_json，实际列名是 "metadata"——保留字转义）
	var metadataJSON sql.NullString
	if err = tx.QueryRow(`SELECT metadata FROM papers WHERE id=?`, paperID).Scan(&metadataJSON); err != nil {
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
		`UPDATE papers SET read_status='skimmed', metadata=? WHERE id=?`,
		mustJSON(metadata), paperID,
	); err != nil {
		return "", fmt.Errorf("papers update: %w", err)
	}

	// 2c. prompt_traces 插入（成本观测，随领域变化同事务）
	if trace != nil {
		if _, err = tx.Exec(
			`INSERT INTO prompt_traces (id, paper_id, stage, provider, model, prompt_digest,
			 input_tokens, output_tokens, input_cost_usd, output_cost_usd, total_cost_usd, created_at)
			 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, $1)`,
			newCoreID(), nullIfEmpty(stringOr(trace["paper_id"])),
			stringOr(trace["stage"]), stringOr(trace["provider"]), stringOr(trace["model"]),
			stringOr(trace["prompt_digest"]),
			jsonInt(trace["input_tokens"]), jsonInt(trace["output_tokens"]),
			jsonFloat(trace["input_cost_usd"]), jsonFloat(trace["output_cost_usd"]),
			jsonFloat(trace["total_cost_usd"]),
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
	err = tx.QueryRow(`SELECT id FROM analysis_reports WHERE paper_id=?`, paperID).Scan(&existingReport)
	switch {
	case err == sql.ErrNoRows:
		if _, err = tx.Exec(
			`INSERT INTO analysis_reports (id, paper_id, deep_dive_md, key_insights, created_at, updated_at)
			 VALUES (?, ?, ?, '{}', $1, $2)`,
			newCoreID(), paperID, deepMD,
		); err != nil {
			return "", fmt.Errorf("analysis_reports insert: %w", err)
		}
	case err != nil:
		return "", err
	default:
		// key_insights 保留既有 skim 内容（Python 语义：合并而非覆盖）
		if _, err = tx.Exec(
			`UPDATE analysis_reports SET deep_dive_md=?, updated_at=$1 WHERE paper_id=?`,
			deepMD, paperID,
		); err != nil {
			return "", fmt.Errorf("analysis_reports update: %w", err)
		}
	}

	// read_status 只升不降（unread→skimmed→deep_read）
	if _, err = tx.Exec(
		`UPDATE papers SET read_status='deep_read'
		 WHERE id=? AND (read_status='unread' OR read_status='skimmed')`,
		paperID,
	); err != nil {
		return "", fmt.Errorf("papers read_status: %w", err)
	}

	if trace != nil {
		if _, err = tx.Exec(
			`INSERT INTO prompt_traces (id, paper_id, stage, provider, model, prompt_digest,
			 input_tokens, output_tokens, input_cost_usd, output_cost_usd, total_cost_usd, created_at)
			 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, $1)`,
			newCoreID(), nullIfEmpty(stringOr(trace["paper_id"])),
			stringOr(trace["stage"]), stringOr(trace["provider"]), stringOr(trace["model"]),
			stringOr(trace["prompt_digest"]),
			jsonInt(trace["input_tokens"]), jsonInt(trace["output_tokens"]),
			jsonFloat(trace["input_cost_usd"]), jsonFloat(trace["output_cost_usd"]),
			jsonFloat(trace["total_cost_usd"]),
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
		`UPDATE papers SET embedding_vec=?, updated_at=$1 WHERE id=?`,
		mustJSON(vector), paperID,
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

// FailTask 失败上报（core 表；重试/dead_letter 语义与 Python durable 一致）
func (s *CoreStore) FailTask(taskID, executorID, leaseToken, errorClass, message string) (string, error) {
	var status string
	var attemptCount, maxAttempts int
	var leaseTokenDB sql.NullString
	err := s.DB.QueryRow(
		`SELECT status, attempt_count, max_attempts, lease_token FROM core_tasks WHERE id=?`,
		taskID,
	).Scan(&status, &attemptCount, &maxAttempts, &leaseTokenDB)
	if err != nil {
		return "", err
	}
	if status != "leased" || !leaseTokenDB.Valid || leaseTokenDB.String != leaseToken {
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
	now := nowParam()
	if _, err = tx.Exec(
		`UPDATE core_tasks SET status=?, lease_token=NULL, lease_expires_at=NULL, last_error=? WHERE id=?`,
		newStatus, errorClass+": "+message, taskID,
	); err != nil {
		return "", err
	}
	if _, err = tx.Exec(
		`UPDATE core_attempts SET status='failed', error_class=?, finished_at=?
		 WHERE task_id=? AND fencing_token=? AND status='running'`,
		errorClass, now, taskID, attemptCount,
	); err != nil {
		return "", err
	}
	// Job 收敛：全部终态 → failed/partially（单任务切片：失败 → failed）
	if newStatus == "dead_letter" {
		if _, err = tx.Exec(
			`UPDATE core_jobs SET status='failed', finished_at=? WHERE id=? AND status='running'`,
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
	rows, err := s.DB.Query(
		`SELECT id, attempt_count, max_attempts FROM core_tasks
		 WHERE status='leased' AND lease_expires_at < detime('now') - make_interval(secs => ?)`,
		fmt.Sprintf("-%d seconds", backoffS),
	)
	if err != nil {
		return nil, err
	}
	type expired struct {
		id           string
		attemptCount int
		maxAttempts  int
	}
	var list []expired
	for rows.Next() {
		var e expired
		if err = rows.Scan(&e.id, &e.attemptCount, &e.maxAttempts); err != nil {
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
		if _, err = s.DB.Exec(
			`UPDATE core_tasks SET status=?, lease_token=NULL, lease_expires_at=NULL WHERE id=?`,
			newStatus, e.id,
		); err != nil {
			return nil, err
		}
		if _, err = s.DB.Exec(
			`UPDATE core_attempts SET status='failed', error_class='lease_expired', finished_at=?
			 WHERE task_id=? AND fencing_token=? AND status='running'`,
			nowParam(), e.id, e.attemptCount,
		); err != nil {
			return nil, err
		}
		out[e.id] = map[bool]string{true: "requeued", false: "dead_letter"}[newStatus == "queued"]
	}
	return out, nil
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
		 VALUES (?, 'claim_extraction', 'api', ?, ?, 'succeeded', $1)`,
		runID, mustJSON([]string{paperID}), modelPolicy,
	); err != nil {
		return "", fmt.Errorf("research_runs insert: %w", err)
	}

	// ---- SourceVersion 幂等回补（get_current → 无则 create v1）----
	svID := ""
	err = tx.QueryRow(
		`SELECT id FROM source_versions WHERE paper_id=? AND is_current=1 LIMIT 1`, paperID,
	).Scan(&svID)
	if err == sql.ErrNoRows {
		svID = newCoreID()
		// identity_hash: sha256(json({abstract, arxiv_id, title}, sort_keys))
		var abstract, arxivID, title string
		_ = tx.QueryRow(
			`SELECT abstract, arxiv_id, title FROM papers WHERE id=?`, paperID,
		).Scan(&abstract, &arxivID, &title)
		identityJSON := mustJSON(map[string]string{
			"abstract": abstract, "arxiv_id": arxivID, "title": title,
		})
		contentHash := sha256Hex(identityJSON)
		// version_label = max+1
		var maxLabel int
		_ = tx.QueryRow(
			`SELECT COALESCE(MAX(version_label), 0) FROM source_versions WHERE paper_id=?`, paperID,
		).Scan(&maxLabel)
		// 降级旧 current
		if _, err = tx.Exec(
			`UPDATE source_versions SET is_current=0 WHERE paper_id=? AND is_current=1`, paperID,
		); err != nil {
			return "", err
		}
		if _, err = tx.Exec(
			`INSERT INTO source_versions (id, paper_id, version_label, content_hash, detected_by, is_current, created_at)
			 VALUES (?, ?, ?, ?, 'ingest', 1, $1)`,
			svID, paperID, maxLabel+1, contentHash,
		); err != nil {
			return "", fmt.Errorf("source_versions insert: %w", err)
		}
		// outbox: source_version_detected
		if _, err = tx.Exec(
			`INSERT INTO research_events (id, type, aggregate_type, aggregate_id, actor, payload, occurred_at)
			 VALUES (?, 'source_version_detected', 'source_version', ?, 'system', ?, $1)`,
			newCoreID(), svID, mustJSON(map[string]any{"paper_id": paperID, "version_label": maxLabel + 1}),
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
			`SELECT COUNT(*) FROM evidence WHERE source_version_id=? AND quote=?`,
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
			 VALUES (?, ?, ?, 'papermind', 'draft', ?, ?, $1, $2)`,
			claimID, statement, statementZh, certainty, runID,
		); err != nil {
			return "", fmt.Errorf("claims insert: %w", err)
		}

		// outbox: claim_proposed
		claimPayload := mustJSON(map[string]any{
			"statement": statement, "origin": "papermind", "status": "draft", "certainty": certainty,
		})
		if _, err = tx.Exec(
			`INSERT INTO research_events (id, type, aggregate_type, aggregate_id, actor, run_id, payload, occurred_at)
			 VALUES (?, 'claim_proposed', 'claim', ?, 'papermind', ?, ?, $1)`,
			newCoreID(), claimID, runID, claimPayload,
		); err != nil {
			return "", err
		}

		// Evidence（quote+locator 存在时创建，fingerprint 去重）
		if quote != "" {
			fingerprint := evidenceFingerprint(claimID, svID, "text_passage", locator, quote)
			evID := newCoreID()
			if _, err = tx.Exec(
				`INSERT INTO evidence (id, claim_id, source_version_id, kind, stance, locator, quote, fingerprint, run_id, created_at)
				 VALUES (?, ?, ?, 'text_passage', 'supports', ?, ?, ?, ?, $1)`,
				evID, claimID, svID, locator, quote, fingerprint, runID,
			); err != nil {
				return "", fmt.Errorf("evidence insert: %w", err)
			}
			// outbox: evidence_extracted
			evPayload := mustJSON(map[string]any{"claim_id": claimID, "source_version_id": svID, "quote": quote})
			if _, err = tx.Exec(
				`INSERT INTO research_events (id, type, aggregate_type, aggregate_id, actor, run_id, payload, occurred_at)
				 VALUES (?, 'evidence_extracted', 'evidence', ?, 'system', ?, ?, $1)`,
				newCoreID(), evID, runID, evPayload,
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
			 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, $1)`,
			newCoreID(), nullIfEmpty(stringOr(trace["paper_id"])),
			stringOr(trace["stage"]), stringOr(trace["provider"]), stringOr(trace["model"]),
			stringOr(trace["prompt_digest"]),
			jsonInt(trace["input_tokens"]), jsonInt(trace["output_tokens"]),
			jsonFloat(trace["input_cost_usd"]), jsonFloat(trace["output_cost_usd"]),
			jsonFloat(trace["total_cost_usd"]),
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

func jobIDOf(tx *sql.Tx, taskID string) string {
	var jobID string
	_ = tx.QueryRow(`SELECT job_id FROM core_tasks WHERE id=?`, taskID).Scan(&jobID)
	return jobID
}
