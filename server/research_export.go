package main

// research_export.go：Research Object 导出（JSON + Markdown）。

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strings"
	"time"
)

// handleResearchExport：GET /research/questions/{id}/export?format=json|markdown。
func (s *Server) handleResearchExport(w http.ResponseWriter, r *http.Request) {
	qid := r.PathValue("question_id")
	format := r.URL.Query().Get("format")
	if format == "" {
		format = "json"
	}

	// 1. question view（复用 handleResearchQuestion 逻辑）
	var qID, qTitle, qText, qStatus string
	var watchTerms []byte
	var qCreated, qUpdated *time.Time
	err := s.db.QueryRow(
		`SELECT id, title, question, status, watch_terms, created_at, updated_at
		 FROM research_questions WHERE id=$1`, qid,
	).Scan(&qID, &qTitle, &qText, &qStatus, &watchTerms, &qCreated, &qUpdated)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "研究问题不存在"})
		return
	}

	// 2. claims
	type claimRow struct {
		ID, Statement, StatementZh, Origin, Status, Certainty string
		SupersededBy, RunID                                   *string
		CreatedAt                                             time.Time
	}
	var claims []claimRow
	claimRows, err := s.db.Query(
		`SELECT id, statement, COALESCE(statement_zh,''), origin::text, status::text,
			certainty::text, superseded_by_id, run_id, created_at
		 FROM claims WHERE research_question_id=$1 ORDER BY id DESC`, qid)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer claimRows.Close()
	claimIDs := []string{}
	for claimRows.Next() {
		var c claimRow
		if err := claimRows.Scan(&c.ID, &c.Statement, &c.StatementZh, &c.Origin, &c.Status, &c.Certainty, &c.SupersededBy, &c.RunID, &c.CreatedAt); err != nil {
			continue
		}
		claims = append(claims, c)
		claimIDs = append(claimIDs, c.ID)
	}

	// 3. evidence + source_versions + papers
	type evidenceRow struct {
		ID, ClaimID, Kind, Stance, ExtractedBy string
		Locator, Quote, Conditions             []byte
		SourceVersionID                        string
	}
	type svRow struct {
		ID              string
		VersionLabel    int
		ExternalVersion *string
		ContentHash     string
		FetchedAt       *time.Time
		IsCurrent       bool
		PaperID         string
	}
	type paperRow struct {
		ID, Title, ArxivID *string
	}
	evidenceList := []map[string]any{}
	svMap := map[string]*svRow{}
	paperMap := map[string]*paperRow{}
	if len(claimIDs) > 0 {
		placeholders := make([]string, len(claimIDs))
		evArgs := make([]any, len(claimIDs))
		for i := range claimIDs {
			placeholders[i] = "$" + itoa(i+1)
			evArgs[i] = claimIDs[i]
		}
		evRows, err := s.db.Query(
			`SELECT e.id, e.claim_id, e.kind::text, e.stance::text, e.locator, e.quote,
				e.experiment_conditions, e.extracted_by::text, e.source_version_id,
				sv.id, sv.version_label, sv.external_version, sv.content_hash, sv.fetched_at, sv.is_current,
				p.id, p.title, p.arxiv_id
			 FROM evidence e
			 JOIN source_versions sv ON e.source_version_id = sv.id
			 JOIN papers p ON sv.paper_id = p.id
			 WHERE e.claim_id IN (`+strings.Join(placeholders, ",")+
				`) ORDER BY e.id`, evArgs...)
		if err == nil {
			defer evRows.Close()
			for evRows.Next() {
				var e evidenceRow
				var sv svRow
				var p paperRow
				if err := evRows.Scan(&e.ID, &e.ClaimID, &e.Kind, &e.Stance, &e.Locator, &e.Quote,
					&e.Conditions, &e.ExtractedBy, &e.SourceVersionID,
					&sv.ID, &sv.VersionLabel, &sv.ExternalVersion, &sv.ContentHash, &sv.FetchedAt, &sv.IsCurrent,
					&p.ID, &p.Title, &p.ArxivID); err != nil {
					continue
				}
				evidenceList = append(evidenceList, map[string]any{
					"id": e.ID, "claim_id": e.ClaimID, "kind": e.Kind, "stance": e.Stance,
					"locator": jsonParseObj(string(e.Locator)), "quote": byteStrOrNull(e.Quote),
					"experiment_conditions": jsonParseObj(string(e.Conditions)),
					"extracted_by":          e.ExtractedBy, "source_version_id": e.SourceVersionID,
				})
				svMap[sv.ID] = &sv
				paperMap[sv.ID] = &p
			}
		}
	}

	// 4. relations
	type relationRow struct {
		ID, SubjectID, ObjectID, Predicate, Origin string
	}
	relations := []map[string]any{}
	if len(claimIDs) > 0 {
		ph := make([]string, len(claimIDs))
		relArgs := make([]any, len(claimIDs))
		for i := range claimIDs {
			relArgs[i] = claimIDs[i]
		}
		for i := range claimIDs {
			ph[i] = "$" + itoa(i+1)
		}
		relRows, err := s.db.Query(
			`SELECT id, subject_claim_id, object_claim_id, predicate::text, origin::text
			 FROM claim_relations
			 WHERE subject_claim_id IN (`+strings.Join(ph, ",")+
				`) OR object_claim_id IN (`+strings.Join(ph, ",")+")", relArgs...)
		if err == nil {
			defer relRows.Close()
			for relRows.Next() {
				var r relationRow
				if relRows.Scan(&r.ID, &r.SubjectID, &r.ObjectID, &r.Predicate, &r.Origin) == nil {
					relations = append(relations, map[string]any{
						"id": r.ID, "subject_claim_id": r.SubjectID,
						"object_claim_id": r.ObjectID, "predicate": r.Predicate, "origin": r.Origin,
					})
				}
			}
		}
	}

	// 5. source_versions
	sourceVersions := []map[string]any{}
	svIDs := make([]string, 0, len(svMap))
	for id := range svMap {
		svIDs = append(svIDs, id)
	}
	sort.Strings(svIDs)
	for _, svID := range svIDs {
		sv := svMap[svID]
		p := paperMap[svID]
		item := map[string]any{
			"id": sv.ID, "version_label": sv.VersionLabel,
			"external_version": jsonStrOrNull(sv.ExternalVersion), "content_hash": sv.ContentHash,
			"fetched_at": isoTime(sv.FetchedAt), "is_current": sv.IsCurrent,
			"paper": map[string]any{"id": sv.PaperID},
		}
		if p != nil {
			item["paper"] = map[string]any{"id": p.ID, "title": jsonStrOrNull(p.Title), "arxiv_id": jsonStrOrNull(p.ArxivID)}
		}
		sourceVersions = append(sourceVersions, item)
	}

	// 6. research runs
	runs := []map[string]any{}
	runIDSet := map[string]bool{}
	// 从 claims 表直接查 run_ids
	runRows, err := s.db.Query(
		`SELECT DISTINCT run_id FROM claims WHERE research_question_id=$1 AND run_id IS NOT NULL`, qid)
	if err == nil {
		defer runRows.Close()
		var runIDs []string
		for runRows.Next() {
			var rid string
			if runRows.Scan(&rid) == nil {
				runIDs = append(runIDs, rid)
			}
		}
		for _, rid := range runIDs {
			var rID, kind, trigger, status string
			var startedAt, finishedAt sql.NullTime
			if err := s.db.QueryRow(
				`SELECT id, kind, trigger::text, status::text, started_at, finished_at
				 FROM research_runs WHERE id=$1`, rid,
			).Scan(&rID, &kind, &trigger, &status, &startedAt, &finishedAt); err == nil {
				runIDSet[rid] = true
				runs = append(runs, map[string]any{
					"id": rID, "kind": kind, "trigger": trigger, "status": status,
					"started_at": isoNullTime(startedAt), "finished_at": isoNullTime(finishedAt),
				})
			}
		}
	}

	// 7. 组装 research_object
	questionView := map[string]any{
		"id": qID, "title": qTitle, "question": qText, "status": qStatus,
		"claim_counts": map[string]any{"by_status": map[string]int{}, "by_certainty": map[string]int{}},
	}
	claimsJSON := []map[string]any{}
	for _, c := range claims {
		claimsJSON = append(claimsJSON, map[string]any{
			"id": c.ID, "statement": c.Statement, "statement_zh": jsonStrOrNull(&c.StatementZh),
			"origin": c.Origin, "status": c.Status, "certainty": c.Certainty,
			"created_at": c.CreatedAt.UTC().Format(time.RFC3339Nano),
		})
	}

	ro := map[string]any{
		"ro_type": "papermind-research-object", "ro_version": 1,
		"question": questionView, "claims": claimsJSON, "evidence": evidenceList,
		"relations": relations, "source_versions": sourceVersions,
		"provenance": map[string]any{"research_runs": runs, "claim_events_count": len(claimsJSON)},
	}
	canonical, _ := json.Marshal(ro)
	hash := sha256.Sum256(canonical)
	contentHash := "sha256:" + hex.EncodeToString(hash[:])
	generatedAt := time.Now().UTC().Format(time.RFC3339Nano)

	if format == "markdown" {
		md := s.renderResearchMarkdown(ro)
		w.Header().Set("Content-Type", "text/markdown; charset=utf-8")
		_, _ = w.Write([]byte(md))
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"content_hash": contentHash, "generated_at": generatedAt, "research_object": ro,
	})
}

// renderResearchMarkdown：Research Object 的人读渲染。
func (s *Server) renderResearchMarkdown(ro map[string]any) string {
	var sb strings.Builder
	sb.WriteString("# PaperMind Research Object\n\n")
	if q, ok := ro["question"].(map[string]any); ok {
		sb.WriteString("## " + fmt.Sprintf("%v", q["title"]) + "\n\n")
		sb.WriteString(fmt.Sprintf("%v\n\n", q["question"]))
	}
	if claims, ok := ro["claims"].([]map[string]any); ok {
		sb.WriteString("## Claims\n\n")
		for _, c := range claims {
			sb.WriteString(fmt.Sprintf("- **%v** (%v): %v\n", c["status"], c["certainty"], c["statement"]))
		}
		sb.WriteString("\n")
	}
	if evs, ok := ro["evidence"].([]map[string]any); ok {
		sb.WriteString("## Evidence\n\n")
		for _, e := range evs {
			sb.WriteString(fmt.Sprintf("- [%v] %v\n", e["stance"], e["quote"]))
		}
		sb.WriteString("\n")
	}
	return sb.String()
}
