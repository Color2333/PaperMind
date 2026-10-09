package main

// util.go：papers/research 共用的小工具（JSON 形状对齐 Python 序列化）。

import (
	"encoding/json"
	"strconv"
	"strings"
)

func atoiOr(s string, def int) int {
	if v, err := strconv.Atoi(s); err == nil {
		return v
	}
	return def
}

func itoa(v int) string {
	return strconv.Itoa(v)
}

func jsonRawOrNull(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func jsonStrOrNull(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// jsonParseArray：JSON 数组文本 → []any（空/坏值 → 空数组，与 Python [] 对齐）
func jsonParseArray(s string) []any {
	if s == "" {
		return []any{}
	}
	var out []any
	if err := json.Unmarshal([]byte(s), &out); err != nil {
		return []any{}
	}
	return out
}

// jsonParseObj：JSON 对象文本 → map（空/坏值 → 空对象）
func jsonParseObj(s string) map[string]any {
	if s == "" {
		return map[string]any{}
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(s), &out); err != nil {
		return map[string]any{}
	}
	return out
}

var _ = strings.TrimSpace

// topicsForPaper：批量查 paper → topic name 列表（与 get_topic_names_for_papers 一致）
func (s *Server) topicsForPaper(paperID string) []string {
	rows, err := s.db.Query(
		`SELECT ts.name FROM paper_topics pt
		 JOIN topic_subscriptions ts ON pt.topic_id = ts.id
		 WHERE pt.paper_id = $1`, paperID)
	if err != nil {
		return []string{}
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err == nil {
			out = append(out, name)
		}
	}
	return out
}

// tagsForPaper：paper → tags（id/name/color）
func (s *Server) tagsForPaper(paperID string) []map[string]any {
	rows, err := s.db.Query(
		`SELECT t.id, t.name, t.color FROM paper_tags ptg
		 JOIN tags t ON ptg.tag_id = t.id
		 WHERE ptg.paper_id = $1`, paperID)
	if err != nil {
		return []map[string]any{}
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var id, name, color string
		if err := rows.Scan(&id, &name, &color); err == nil {
			out = append(out, map[string]any{"id": id, "name": name, "color": color})
		}
	}
	return out
}
