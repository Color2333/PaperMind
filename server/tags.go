package main

// tags.go：标签管理 8 端点（与 apps/api/routers/tags.py +
// packages/application/commands/tags.py 逐契约对齐）。

import (
	"encoding/json"
	"net/http"
	"regexp"
	"strings"
)

var hexColorPattern = regexp.MustCompile(`^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$`)

func tagDict(id, name, color string, paperCount int, createdAt, updatedAt *string) map[string]any {
	out := map[string]any{
		"id": id, "name": name, "color": color, "paper_count": paperCount,
		"created_at": (*string)(nil), "updated_at": (*string)(nil),
	}
	if createdAt != nil {
		out["created_at"] = *createdAt
	}
	if updatedAt != nil {
		out["updated_at"] = *updatedAt
	}
	return out
}

// handleListTags：GET /tags。
func (s *Server) handleListTags(w http.ResponseWriter, r *http.Request) {
	rows, err := s.db.Query(
		`SELECT t.id, t.name, t.color,
			(SELECT COUNT(*) FROM paper_tags ptg WHERE ptg.tag_id = t.id) AS paper_count,
			TO_CHAR(t.created_at, 'YYYY-MM-DD"T"HH24:MI:SSOF'), TO_CHAR(t.updated_at, 'YYYY-MM-DD"T"HH24:MI:SSOF')
		FROM tags t ORDER BY t.created_at`)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var id, name, color, createdAt, updatedAt string
		var count int
		if err := rows.Scan(&id, &name, &color, &count, &createdAt, &updatedAt); err == nil {
			items = append(items, tagDict(id, name, color, count, &createdAt, &updatedAt))
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items})
}

// handleCreateTag：POST /tags?name=&color=。
func (s *Server) handleCreateTag(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimSpace(r.URL.Query().Get("name"))
	color := r.URL.Query().Get("color")
	if color == "" {
		color = "#3b82f6"
	}
	if name == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "标签名称不能为空"})
		return
	}
	if !hexColorPattern.MatchString(color) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid color"})
		return
	}
	var id, createdAt, updatedAt string
	err := s.db.QueryRow(
		`INSERT INTO tags (id, name, color, created_at, updated_at)
		 VALUES (gen_random_uuid()::text, $1, $2, now()::timestamp, now()::timestamp)
		 ON CONFLICT (name) DO UPDATE SET color = EXCLUDED.color, updated_at = now()::timestamp
		 RETURNING id, created_at::text, updated_at::text`,
		name, color,
	).Scan(&id, &createdAt, &updatedAt)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": id, "name": name, "color": color, "paper_count": 0})
}

// handleUpdateTag：PATCH /tags/{id}?name=&color=。
func (s *Server) handleUpdateTag(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("tag_id")
	name := r.URL.Query().Get("name")
	color := r.URL.Query().Get("color")
	sets := []string{}
	args := []any{}
	if name != "" {
		sets = append(sets, "name=$"+itoa(len(sets)+1))
		args = append(args, name)
	}
	if color != "" {
		if !hexColorPattern.MatchString(color) {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "invalid color"})
			return
		}
		sets = append(sets, "color=$"+itoa(len(sets)+1))
		args = append(args, color)
	}
	if len(sets) == 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "nothing to update"})
		return
	}
	sets = append(sets, "updated_at=now()::timestamp")
	res, err := s.db.Exec("UPDATE tags SET "+strings.Join(sets, ", ")+" WHERE id=$"+itoa(len(args)+1),
		append(args, id)...)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "标签不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": id, "name": name, "color": color})
}

// handleDeleteTag：DELETE /tags/{id}。
func (s *Server) handleDeleteTag(w http.ResponseWriter, r *http.Request) {
	res, err := s.db.Exec("DELETE FROM tags WHERE id=$1", r.PathValue("tag_id"))
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	if n, _ := res.RowsAffected(); n == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "标签不存在"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
}

// handleGetPaperTags：GET /papers/{id}/tags。
func (s *Server) handleGetPaperTags(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	var exists bool
	if err := s.db.QueryRow("SELECT EXISTS(SELECT 1 FROM papers WHERE id=$1)", paperID).Scan(&exists); err != nil || !exists {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "paper not found"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": s.tagsForPaper(paperID)})
}

// handleAddPaperTag：POST /papers/{id}/tags?tag_id=。
func (s *Server) handleAddPaperTag(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	tagID := r.URL.Query().Get("tag_id")
	var exists bool
	if err := s.db.QueryRow("SELECT EXISTS(SELECT 1 FROM tags WHERE id=$1)", tagID).Scan(&exists); err != nil || !exists {
		writeJSON(w, http.StatusNotFound, map[string]string{"detail": "标签不存在"})
		return
	}
	if _, err := s.db.Exec(
		`INSERT INTO paper_tags (id, paper_id, tag_id, created_at) VALUES ($1, $2, $3, now()::timestamp)
		 ON CONFLICT DO NOTHING`, newUUID(), paperID, tagID,
	); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": s.tagsForPaper(paperID)})
}

// handleRemovePaperTag：DELETE /papers/{id}/tags/{tag_id}。
func (s *Server) handleRemovePaperTag(w http.ResponseWriter, r *http.Request) {
	_, err := s.db.Exec(
		"DELETE FROM paper_tags WHERE paper_id=$1 AND tag_id=$2",
		r.PathValue("paper_id"), r.PathValue("tag_id"),
	)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": s.tagsForPaper(r.PathValue("paper_id"))})
}

// handleBatchPaperTags：POST /papers/{id}/tags/batch（body: [tag_id,...]）。
func (s *Server) handleBatchPaperTags(w http.ResponseWriter, r *http.Request) {
	paperID := r.PathValue("paper_id")
	var tagIDs []string
	if err := json.NewDecoder(r.Body).Decode(&tagIDs); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "bad json"})
		return
	}
	// R05：整批替换必须事务化——删除后插入失败要回滚
	tx, err := s.db.Begin()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	defer tx.Rollback()
	if _, err := tx.Exec("DELETE FROM paper_tags WHERE paper_id=$1", paperID); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	for _, tagID := range tagIDs {
		if _, err := tx.Exec(
			"INSERT INTO paper_tags (id, paper_id, tag_id, created_at) VALUES ($1, $2, $3, now()::timestamp) ON CONFLICT DO NOTHING",
			newUUID(), paperID, tagID,
		); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
			return
		}
	}
	if err := tx.Commit(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": s.tagsForPaper(paperID)})
}
