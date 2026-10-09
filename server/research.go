package main

// research.go：研究状态只读面（Phase 1）——与
// apps/api/routers/research.py + packages/application/queries/research_state.py
// 逐契约对齐（get_research_question / list_claims / get_claim_evidence / diff）。

import (
	"net/http"
	"time"
)

func isoTime(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.Format(time.RFC3339Nano)
}

// handleResearchQuestion：GET /research/questions/{id}。
func (s *Server) handleResearchQuestion(w http.ResponseWriter, r *http.Request) {
	qid := r.PathValue("question_id")
	var id, title, question, status string
	var watchTerms []byte
	var createdAt, updatedAt *time.Time
	err := s.db.QueryRow(
		`SELECT id, title, question, status, watch_terms, created_at, updated_at
		 FROM research_questions WHERE id = $1`, qid,
	).Scan(&id, &title, &question, &status, &watchTerms, &createdAt, &updatedAt)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "研究问题不存在"})
		return
	}

	byStatus := map[string]int{}
	byCertainty := map[string]int{}
	rows, err := s.db.Query(
		`SELECT status, COUNT(*) FROM claims WHERE research_question_id=$1 GROUP BY status`, qid)
	if err == nil {
		for rows.Next() {
			var st string
			var n int
			if rows.Scan(&st, &n) == nil {
				byStatus[st] = n
			}
		}
		rows.Close()
	}
	rows2, err := s.db.Query(
		`SELECT certainty, COUNT(*) FROM claims WHERE research_question_id=$1 GROUP BY certainty`, qid)
	if err == nil {
		for rows2.Next() {
			var c string
			var n int
			if rows2.Scan(&c, &n) == nil {
				byCertainty[c] = n
			}
		}
		rows2.Close()
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id": id, "title": title, "question": question, "status": status,
		"watch_terms": jsonParseArray(string(watchTerms)),
		"claim_counts": map[string]any{
			"by_status":    byStatus,
			"by_certainty": byCertainty,
		},
		"created_at": isoTime(createdAt), "updated_at": isoTime(updatedAt),
	})
}

// handleListClaims：GET /research/questions/{id}/claims?status=&limit=。
func (s *Server) handleListClaims(w http.ResponseWriter, r *http.Request) {
	qid := r.PathValue("question_id")
	statusFilter := r.URL.Query().Get("status")
	limit := atoiOr(r.URL.Query().Get("limit"), 100)
	if limit < 1 || limit > 500 {
		limit = 100
	}

	var questionExists bool
	if err := s.db.QueryRow(
		"SELECT EXISTS(SELECT 1 FROM research_questions WHERE id=$1)", qid,
	).Scan(&questionExists); err != nil || !questionExists {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "研究问题不存在"})
		return
	}

	args := []any{qid}
	where := "research_question_id = $1"
	if statusFilter != "" {
		where += " AND status = $" + itoa(len(args)+1)
		args = append(args, statusFilter)
	}
	// UUIDv7 主键即时间倒序（与 Python list_by_question 一致）
	rows, err := s.db.Query(
		`SELECT id, statement, COALESCE(statement_zh,''), origin::text, status::text,
			certainty::text, superseded_by_id, run_id, created_at
		 FROM claims WHERE `+where+` ORDER BY id DESC`, args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()

	items := []map[string]any{}
	for rows.Next() {
		var id, statement, origin, status, certainty string
		var statementZh *string
		var supersededBy, runID *string
		var createdAt time.Time
		if err := rows.Scan(&id, &statement, &statementZh, &origin, &status, &certainty, &supersededBy, &runID, &createdAt); err != nil {
			continue
		}
		items = append(items, map[string]any{
			"id": id, "statement": statement, "statement_zh": strFromAny(statementZh),
			"origin": origin, "status": status, "certainty": certainty,
			"superseded_by_id": jsonStrOrNull(supersededBy), "run_id": jsonStrOrNull(runID),
			"created_at": createdAt.UTC().Format(time.RFC3339Nano),
		})
	}
	if len(items) > limit {
		items = items[:limit]
	}
	// 每条的证据计数
	counts := map[string]int{}
	for _, it := range items {
		var n int
		if err := s.db.QueryRow(
			"SELECT COUNT(*) FROM evidence WHERE claim_id=$1", it["id"]).Scan(&n); err == nil {
			counts[it["id"].(string)] = n
		}
	}
	for _, it := range items {
		id := it["id"].(string)
		it["evidence_count"] = counts[id]
	}
	writeJSON(w, http.StatusOK, map[string]any{"question_id": qid, "items": items})
}

// handleClaimEvidence：GET /research/claims/{id}/evidence。
func (s *Server) handleClaimEvidence(w http.ResponseWriter, r *http.Request) {
	claimID := r.PathValue("claim_id")
	var claim struct {
		ID, Statement, Origin, Status, Certainty string
		StatementZh, UserNote, ConfirmedBy       *string
		RunID                                    *string
		CreatedAt                                time.Time
	}
	err := s.db.QueryRow(
		`SELECT id, statement, origin::text, status::text, certainty::text,
			statement_zh, user_note, confirmed_by, run_id, created_at
		 FROM claims WHERE id=$1`, claimID,
	).Scan(&claim.ID, &claim.Statement, &claim.Origin, &claim.Status, &claim.Certainty,
		&claim.StatementZh, &claim.UserNote, &claim.ConfirmedBy, &claim.RunID, &claim.CreatedAt)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "Claim 不存在"})
		return
	}

	rows, err := s.db.Query(
		`SELECT e.id, e.kind::text, e.stance::text, e.locator, e.quote,
			e.experiment_conditions, e.extracted_by::text,
			sv.id, sv.version_label, sv.external_version, sv.content_hash,
			p.id, p.title, p.arxiv_id, p.doi
		 FROM evidence e
		 JOIN source_versions sv ON e.source_version_id = sv.id
		 JOIN papers p ON sv.paper_id = p.id
		 WHERE e.claim_id=$1 ORDER BY e.id`, claimID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()

	evidenceItems := []map[string]any{}
	for rows.Next() {
		var id, kind, stance, extractedBy string
		var locator []byte
		var quote, conditions []byte
		var svID string
		var versionLabel int
		var contentHash *string
		var externalVersion, pID, pTitle, pArxivID, pDOI *string
		if err := rows.Scan(&id, &kind, &stance, &locator, &quote, &conditions, &extractedBy,
			&svID, &versionLabel, &externalVersion, &contentHash,
			&pID, &pTitle, &pArxivID, &pDOI); err != nil {
			continue
		}
		evidenceItems = append(evidenceItems, map[string]any{
			"id": id, "kind": kind, "stance": stance,
			"locator":               jsonParseObj(string(locator)),
			"quote":                 byteStrOrNull(quote),
			"experiment_conditions": jsonParseObj(string(conditions)),
			"extracted_by":          extractedBy,
			"source_version": map[string]any{
				"id":               svID,
				"version_label":    versionLabel,
				"external_version": jsonStrOrNull(externalVersion),
				"content_hash":     contentHash,
				"paper": map[string]any{
					"id": pID, "title": jsonStrOrNull(pTitle),
					"arxiv_id": jsonStrOrNull(pArxivID), "doi": jsonStrOrNull(pDOI),
				},
			},
		})
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"claim": map[string]any{
			"id": claim.ID, "statement": claim.Statement,
			"statement_zh": jsonStrOrNull(claim.StatementZh),
			"origin":       claim.Origin, "status": claim.Status, "certainty": claim.Certainty,
			"run_id":       jsonStrOrNull(claim.RunID),
			"user_note":    jsonStrOrNull(claim.UserNote),
			"confirmed_by": jsonStrOrNull(claim.ConfirmedBy),
			"created_at":   claim.CreatedAt.UTC().Format(time.RFC3339Nano),
		},
		"evidence": evidenceItems,
	})
}

// handleDiffResearchState：GET /research/questions/{id}/diff?since_hours=。
func (s *Server) handleDiffResearchState(w http.ResponseWriter, r *http.Request) {
	qid := r.PathValue("question_id")
	var questionExists bool
	if err := s.db.QueryRow(
		"SELECT EXISTS(SELECT 1 FROM research_questions WHERE id=$1)", qid,
	).Scan(&questionExists); err != nil || !questionExists {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "研究问题不存在"})
		return
	}

	sinceHours := atoiOr(r.URL.Query().Get("since_hours"), 0)
	args := []any{qid}
	sinceCond := ""
	if sinceHours > 0 {
		args = append(args, time.Now().UTC().Add(-time.Duration(sinceHours)*time.Hour))
		sinceCond = " AND occurred_at >= $" + itoa(len(args))
	}

	// 事件聚合：claim/evidence/relation 三类聚合 ID 属于该问题
	rows, err := s.db.Query(
		`SELECT id, type::text, aggregate_type::text, aggregate_id, actor, payload, occurred_at
		 FROM research_events
		 WHERE (
			(aggregate_type = 'claim' AND aggregate_id IN (SELECT id::text FROM claims WHERE research_question_id = $1))
			OR (aggregate_type = 'evidence' AND aggregate_id IN (SELECT e.id::text FROM evidence e JOIN claims c ON e.claim_id = c.id WHERE c.research_question_id = $1))
			OR (aggregate_type = 'relation' AND aggregate_id IN (SELECT cr.id::text FROM claim_relations cr WHERE cr.subject_claim_id IN (SELECT id FROM claims WHERE research_question_id = $1) OR cr.object_claim_id IN (SELECT id FROM claims WHERE research_question_id = $1)))
		 )`+sinceCond+` ORDER BY id`, args...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()

	items := []map[string]any{}
	for rows.Next() {
		var id, eventType, aggregateType, aggregateID, actor string
		var payload []byte
		var occurredAt time.Time
		if err := rows.Scan(&id, &eventType, &aggregateType, &aggregateID, &actor, &payload, &occurredAt); err != nil {
			continue
		}
		items = append(items, map[string]any{
			"id": id, "event": eventType,
			"diff_kind":    diffKindFor(eventType, payload),
			"aggregate_id": aggregateID, "actor": actor,
			"payload":     jsonParseObj(string(payload)),
			"occurred_at": occurredAt.UTC().Format(time.RFC3339Nano),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"question_id": qid, "items": items})
}

// diffKindFor：事件类型 → diff 语义（与 Python _EVENT_DIFF/_EVIDENCE_DIFF/_RELATION_DIFF 映射一致）。
func diffKindFor(eventType string, payload []byte) string {
	switch eventType {
	case "claim_proposed":
		return "added"
	case "claim_confirmed":
		return "confirmed"
	case "claim_revised":
		return "revised"
	case "claim_invalidated":
		return "invalidated"
	case "retraction_detected":
		return "retraction"
	case "claim_relation_recorded":
		return "relation"
	case "evidence_extracted":
		return "context"
	default:
		return "other"
	}
}

// byteStrOrNull：[]byte → string 或 null。
func byteStrOrNull(b []byte) any {
	if len(b) == 0 {
		return nil
	}
	return string(b)
}

// derefStrPtr：**string（nullable join）→ string 或 null。
func derefStrPtr(sp **string) any {
	if sp == nil || *sp == nil {
		return nil
	}
	return **sp
}
