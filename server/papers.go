package main

// papers.go：papers 读/写面（Phase 1）——与
// apps/api/routers/papers.py + packages/application/queries/papers.py 逐契约对齐。

import (
	"net/http"
	"strings"
)

// handlePapersLatest：GET /papers/latest —— list_papers 全过滤查询移植。
func (s *Server) handlePapersLatest(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	page := atoiOr(q.Get("page"), 1)
	pageSize := atoiOr(q.Get("page_size"), 20)
	folder := q.Get("folder")
	topicID := q.Get("topic_id")
	status := q.Get("status")
	dateStr := q.Get("date")
	search := strings.TrimSpace(q.Get("search"))
	sortBy := q.Get("sort_by")
	sortOrder := q.Get("sort_order")
	category := q.Get("category")

	where := []string{"1=1"}
	args := []any{}
	argN := 0
	addArg := func(v any) string {
		argN++
		args = append(args, v)
		return "$" + itoa(argN)
	}

	if search != "" {
		pat := "%" + search + "%"
		where = append(where, "(p.title ILIKE "+addArg(pat)+" OR p.abstract ILIKE "+addArg(pat)+" OR p.arxiv_id ILIKE "+addArg(pat)+")")
	}
	joinTopic := false
	switch folder {
	case "favorites":
		where = append(where, "p.favorited = true")
	case "recent":
		where = append(where, "p.created_at >= now() - interval '7 days'")
	case "unclassified":
		where = append(where, "NOT EXISTS (SELECT 1 FROM paper_topics pt0 WHERE pt0.paper_id = p.id)")
	}
	if topicID != "" {
		joinTopic = true
		where = append(where, "pt.topic_id = "+addArg(topicID))
	}
	if status == "unread" || status == "skimmed" || status == "deep_read" {
		where = append(where, "p.read_status = "+addArg(status))
	}
	if dateStr != "" {
		dayStart := addArg(dateStr)
		where = append(where, "p.created_at >= "+dayStart+"::date AND p.created_at < "+dayStart+"::date + interval '1 day'")
	}
	if category != "" {
		where = append(where, "p.metadata->'categories' ? "+addArg(category))
	}

	joinClause := ""
	if joinTopic {
		joinClause = " JOIN paper_topics pt ON p.id = pt.paper_id"
	}
	whereSQL := strings.Join(where, " AND ")

	var total int
	if err := s.db.QueryRow(
		"SELECT COUNT(*) FROM papers p"+joinClause+" WHERE "+whereSQL, args...,
	).Scan(&total); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}

	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 500 {
		pageSize = 20
	}
	offset := (page - 1) * pageSize
	sortCol := map[string]string{
		"created_at":       "p.created_at",
		"publication_date": "p.publication_date",
		"title":            "p.title",
	}[sortBy]
	if sortCol == "" {
		sortCol = "p.created_at"
	}
	order := "DESC"
	if sortOrder == "asc" {
		order = "ASC"
	}

	rows, err := s.db.Query(
		`SELECT p.id, p.title, p.arxiv_id, p.abstract,
			TO_CHAR(p.publication_date, 'YYYY-MM-DD'), p.read_status, p.pdf_path,
			p.embedding IS NOT NULL, p.favorited, p.rejected,
			COALESCE(p.metadata->>'categories', '[]'),
			COALESCE(p.metadata->>'keywords', '[]'),
			COALESCE(p.metadata->>'title_zh', ''),
			COALESCE(p.metadata->>'abstract_zh', ''),
			COALESCE(p.metadata::text, '{}')
		FROM papers p`+joinClause+" WHERE "+whereSQL+
			" ORDER BY "+sortCol+" "+order+" NULLS LAST LIMIT $"+itoa(argN+1)+" OFFSET $"+itoa(argN+2),
		append(args, pageSize, offset)...,
	)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()

	items := []map[string]any{}
	for rows.Next() {
		var id, title, arxivID, abstract, pubDate, readStatus, categories, keywords, titleZh, abstractZh, metadata string
		var pdfPath *string
		var hasEmbed, favorited, rejected bool
		if err := rows.Scan(&id, &title, &arxivID, &abstract, &pubDate, &readStatus,
			&pdfPath, &hasEmbed, &favorited, &rejected,
			&categories, &keywords, &titleZh, &abstractZh, &metadata); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
			return
		}
		items = append(items, map[string]any{
			"id":               id,
			"title":            title,
			"arxiv_id":         arxivID,
			"abstract":         abstract,
			"publication_date": jsonStrOrNull(&pubDate),
			"read_status":      readStatus,
			"pdf_path":         jsonStrOrNull(pdfPath),
			"has_embedding":    hasEmbed,
			"favorited":        favorited,
			"rejected":         rejected,
			"categories":       jsonParseArray(categories),
			"keywords":         jsonParseArray(keywords),
			"title_zh":         titleZh,
			"abstract_zh":      abstractZh,
			"metadata":         jsonParseObj(metadata),
			"topics":           s.topicsForPaper(id),
			"tags":             s.tagsForPaper(id),
		})
	}
	totalPages := (total + pageSize - 1) / pageSize
	if totalPages < 1 {
		totalPages = 1
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"items": items, "total": total, "page": page, "page_size": pageSize, "total_pages": totalPages,
	})
}

// handlePaperDetail：GET /papers/{id} —— get_paper 聚合移植。
func (s *Server) handlePaperDetail(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("paper_id")
	var pid, title, arxivID, abstract, readStatus, metadata string
	var pubDate, pdfPath *string
	var favorited, rejected, hasEmbed bool
	err := s.db.QueryRow(
		`SELECT id, title, arxiv_id, abstract, read_status,
			TO_CHAR(publication_date, 'YYYY-MM-DD'), pdf_path,
			COALESCE(metadata::text, '{}'), favorited, rejected,
			embedding IS NOT NULL
		FROM papers WHERE id = $1`, id,
	).Scan(&pid, &title, &arxivID, &abstract, &readStatus,
		&pubDate, &pdfPath, &metadata, &favorited, &rejected, &hasEmbed)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "paper " + id + " not found"})
		return
	}
	metadataJSON := jsonParseObj(metadata)

	var summaryMD, deepDiveMD, keyInsights *string
	var skimScore *float64
	err = s.db.QueryRow(
		`SELECT summary_md, skim_score, key_insights::text, deep_dive_md
		 FROM analysis_reports WHERE paper_id = $1`, id,
	).Scan(&summaryMD, &skimScore, &keyInsights, &deepDiveMD)
	skimData, deepData := map[string]any(nil), map[string]any(nil)
	if err == nil {
		if summaryMD != nil {
			skimData = map[string]any{"summary_md": *summaryMD, "skim_score": skimScore, "key_insights": jsonParseObj(deref(keyInsights))}
		}
		if deepDiveMD != nil {
			deepData = map[string]any{"deep_dive_md": *deepDiveMD}
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id": pid, "title": title, "arxiv_id": arxivID,
		"abstract": abstract, "read_status": readStatus,
		"publication_date": jsonStrOrNull(pubDate), "pdf_path": jsonStrOrNull(pdfPath),
		"favorited": favorited, "rejected": rejected,
		"categories":    jsonParseArray(strFromAny(metadataJSON["categories"])),
		"authors":       jsonParseArray(strFromAny(metadataJSON["authors"])),
		"keywords":      jsonParseArray(strFromAny(metadataJSON["keywords"])),
		"title_zh":      strFromAny(metadataJSON["title_zh"]),
		"abstract_zh":   strFromAny(metadataJSON["abstract_zh"]),
		"metadata":      metadataJSON,
		"has_embedding": hasEmbed,
		"topics":        s.topicsForPaper(pid), "tags": s.tagsForPaper(pid),
		"skim_report": skimData, "deep_report": deepData,
	})
}

// toggles：favorite / reject（PATCH，与 Python toggle 语义一致）。
func (s *Server) handleToggleFavorite(w http.ResponseWriter, r *http.Request) {
	s.toggleBool(w, r.PathValue("paper_id"), "favorited")
}

func (s *Server) handleToggleReject(w http.ResponseWriter, r *http.Request) {
	s.toggleBool(w, r.PathValue("paper_id"), "rejected")
}

func (s *Server) toggleBool(w http.ResponseWriter, id, col string) {
	var cur bool
	if err := s.db.QueryRow("SELECT "+col+" FROM papers WHERE id=$1", id).Scan(&cur); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "paper not found"})
		return
	}
	if _, err := s.db.Exec("UPDATE papers SET "+col+" = NOT "+col+" WHERE id=$1", id); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": id, col: !cur})
}

// strFromAny：metadata map 值（any）→ string。
func strFromAny(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
