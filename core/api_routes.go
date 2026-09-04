// Web API 路由（Phase 1c）：papers / research / jobs 的 Go HTTP 路由。
// database/sql 直查 PG——替代 Python FastAPI 的应用层查询。
package core

import (
	"encoding/json"
	"net/http"
	"strconv"
)

// RegisterAPIRoutes 注册 Web API 路由到 mux。
func (s *Server) RegisterAPIRoutes() {
	s.mux.HandleFunc("GET /api/papers", s.apiListPapers)
	s.mux.HandleFunc("GET /api/papers/{id}", s.apiGetPaper)
	s.mux.HandleFunc("GET /api/papers/search", s.apiSearchPapers)
	s.mux.HandleFunc("GET /api/research/questions/{id}", s.apiGetQuestion)
	s.mux.HandleFunc("GET /api/research/questions/{id}/claims", s.apiListClaims)
	s.mux.HandleFunc("GET /api/research/claims/{id}/evidence", s.apiGetClaimEvidence)
	s.mux.HandleFunc("GET /api/research/questions/{id}/diff", s.apiGetDiff)
	s.mux.HandleFunc("GET /api/jobs", s.apiListJobs)
	s.mux.HandleFunc("GET /api/jobs/{id}", s.apiGetJob)
	s.mux.HandleFunc("GET /api/settings/llm/active", s.apiGetActiveLLM)
}

// ---------- papers ----------

func (s *Server) apiListPapers(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	if limit <= 0 {
		limit = 20
	}
	items, err := s.Store.ListPapers(limit, offset)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	writeAPIJSON(w, map[string]any{"items": items, "total": len(items)})
}

func (s *Server) apiGetPaper(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	paper, err := s.Store.GetPaper(r.PathValue("id"))
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if paper == nil {
		writeAPIJSON(w, map[string]any{"detail": "not found"})
		w.WriteHeader(http.StatusNotFound)
		return
	}
	writeAPIJSON(w, paper)
}

func (s *Server) apiSearchPapers(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	query := r.URL.Query().Get("query")
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 {
		limit = 10
	}
	items, err := s.Store.SearchPapers(query, limit)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	writeAPIJSON(w, map[string]any{"items": items, "total": len(items)})
}

// ---------- research ----------

func (s *Server) apiGetQuestion(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	q, err := s.Store.GetResearchQuestion(r.PathValue("id"))
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if q == nil {
		writeAPIJSON(w, map[string]any{"detail": "not found"})
		w.WriteHeader(http.StatusNotFound)
		return
	}
	writeAPIJSON(w, q)
}

func (s *Server) apiListClaims(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	qID := r.PathValue("id")
	statuses := r.URL.Query()["status"]
	claims, err := s.Store.ListClaims(qID, statuses)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	// 附加 evidence
	for _, c := range claims {
		if ev, err := s.Store.GetClaimEvidence(c["id"].(string)); err == nil {
			c["evidence"] = ev
		}
	}
	writeAPIJSON(w, map[string]any{"items": claims, "total": len(claims)})
}

func (s *Server) apiGetClaimEvidence(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	evidence, err := s.Store.GetClaimEvidence(r.PathValue("id"))
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	writeAPIJSON(w, map[string]any{"items": evidence})
}

func (s *Server) apiGetDiff(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	items, err := s.Store.GetResearchDiff(r.PathValue("id"))
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	writeAPIJSON(w, map[string]any{"items": items})
}

// ---------- jobs ----------

func (s *Server) apiListJobs(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 {
		limit = 20
	}
	items, err := s.Store.JobsList(limit)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	writeAPIJSON(w, map[string]any{"items": items})
}

func (s *Server) apiGetActiveLLM(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	cfg, err := s.Store.GetActiveLLMConfig()
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if cfg == nil {
		writeAPIJSON(w, map[string]any{"active": false})
		return
	}
	writeAPIJSON(w, map[string]any{
		"active": true, "name": cfg.Name, "provider": cfg.Provider,
		"model_skim": cfg.ModelSkim, "model_deep": cfg.ModelDeep,
		"model_embedding": cfg.ModelEmbedding,
	})
}

func (s *Server) apiGetJob(w http.ResponseWriter, r *http.Request) {
	if s.Store == nil {
		s.apiUnavailable(w)
		return
	}
	graph, err := s.Store.JobGraph(jobIDFromPath(r))
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if graph == nil {
		writeAPIJSON(w, map[string]any{"detail": "not found"})
		w.WriteHeader(http.StatusNotFound)
		return
	}
	writeAPIJSON(w, graph)
}

// ---------- helpers ----------

func writeAPIJSON(w http.ResponseWriter, data any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(data)
}

func (s *Server) apiUnavailable(w http.ResponseWriter) {
	http.Error(w, "core store not configured", http.StatusNotImplemented)
}
