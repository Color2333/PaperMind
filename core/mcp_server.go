// MCP Server（Phase 1e）：Model Context Protocol JSON-RPC 2.0 over HTTP。
// 9 个 PaperMind 工具——database/sql 直查 PG，与 Go API 路由共享 store。
package core

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// MCPServer 处理 /mcp 端点（JSON-RPC 2.0）。
type MCPServer struct {
	Store *CoreStore
}

// MCPRequest 是 JSON-RPC 2.0 请求。
type MCPRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

// MCPResponse 是 JSON-RPC 2.0 响应。
type MCPResponse struct {
	JSONRPC string    `json:"jsonrpc"`
	ID      any       `json:"id,omitempty"`
	Result  any       `json:"result,omitempty"`
	Error   *MCPError `json:"error,omitempty"`
}

// MCPError 是 JSON-RPC 2.0 错误。
type MCPError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// MCPTool 是 MCP tools/list 中返回的工具定义。
type MCPTool struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"inputSchema"`
}

// MCPToolCall 是 tools/call 的参数。
type MCPToolCall struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments"`
}

// mcpTools 返回全部 PaperMind MCP 工具定义。
func mcpTools() []MCPTool {
	return []MCPTool{
		{
			Name:        "search_papers",
			Description: "搜索论文库（标题/摘要关键词匹配）",
			InputSchema: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"query": map[string]any{"type": "string", "description": "搜索关键词"},
					"limit": map[string]any{"type": "integer", "description": "最大条数，默认 10"},
				},
				"required": []string{"query"},
			},
		},
		{
			Name:        "get_paper",
			Description: "查看单篇论文详情（摘要/阅读状态/metadata）",
			InputSchema: map[string]any{
				"type":       "object",
				"properties": map[string]any{"paper_id": map[string]any{"type": "string"}},
				"required":   []string{"paper_id"},
			},
		},
		{
			Name:        "get_research_question",
			Description: "查看研究问题详情",
			InputSchema: map[string]any{
				"type":       "object",
				"properties": map[string]any{"question_id": map[string]any{"type": "string"}},
				"required":   []string{"question_id"},
			},
		},
		{
			Name:        "list_claims",
			Description: "列出研究问题下的 Claim（含状态/来源/置信）",
			InputSchema: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"question_id": map[string]any{"type": "string"},
					"statuses":    map[string]any{"type": "array", "items": map[string]any{"type": "string"}},
				},
				"required": []string{"question_id"},
			},
		},
		{
			Name:        "get_claim_evidence",
			Description: "查看 Claim 的全部证据（论文/页码/引用/支持方向）",
			InputSchema: map[string]any{
				"type":       "object",
				"properties": map[string]any{"claim_id": map[string]any{"type": "string"}},
				"required":   []string{"claim_id"},
			},
		},
		{
			Name:        "get_research_diff",
			Description: "查看研究状态变更时间线（新增/加强/削弱/冲突/取代）",
			InputSchema: map[string]any{
				"type":       "object",
				"properties": map[string]any{"question_id": map[string]any{"type": "string"}},
				"required":   []string{"question_id"},
			},
		},
		{
			Name:        "list_jobs",
			Description: "列出最近的 durable Job（状态/类型）",
			InputSchema: map[string]any{
				"type":       "object",
				"properties": map[string]any{"limit": map[string]any{"type": "integer"}},
			},
		},
		{
			Name:        "get_job",
			Description: "查看 durable Job graph（tasks/attempts/进度）",
			InputSchema: map[string]any{
				"type":       "object",
				"properties": map[string]any{"job_id": map[string]any{"type": "string"}},
				"required":   []string{"job_id"},
			},
		},
		{
			Name:        "submit_task",
			Description: "提交 durable 处理任务（skim/deep_read/embed 论文）",
			InputSchema: map[string]any{
				"type": "object",
				"properties": map[string]any{
					"capability": map[string]any{"type": "string", "description": "skim_paper / deep_read_paper / embed_paper"},
					"paper_id":   map[string]any{"type": "string"},
				},
				"required": []string{"capability", "paper_id"},
			},
		},
	}
}

// ServeMCP 处理 /mcp HTTP POST（JSON-RPC 2.0）。
func (s *Server) ServeMCP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req MCPRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeMCPError(w, nil, -32700, "parse error")
		return
	}

	switch req.Method {
	case "initialize":
		writeMCPResult(w, req.ID, map[string]any{
			"protocolVersion": "2024-11-05",
			"capabilities": map[string]any{
				"tools": map[string]any{},
			},
			"serverInfo": map[string]any{
				"name":    "papermind",
				"version": "0.2.0",
			},
		})

	case "notifications/initialized":
		// 通知不需要响应
		w.WriteHeader(http.StatusAccepted)

	case "tools/list":
		tools := mcpTools()
		writeMCPResult(w, req.ID, map[string]any{"tools": tools})

	case "tools/call":
		var params struct {
			Name      string         `json:"name"`
			Arguments map[string]any `json:"arguments"`
		}
		if err := json.Unmarshal(req.Params, &params); err != nil {
			writeMCPError(w, req.ID, -32602, "invalid params")
			return
		}
		result, err := s.callTool(params.Name, params.Arguments)
		if err != nil {
			// 工具执行错误→返回 isError=true 的 result
			writeMCPResult(w, req.ID, map[string]any{
				"content": []map[string]any{
					{"type": "text", "text": "Error: " + err.Error()},
				},
				"isError": true,
			})
			return
		}
		text, _ := json.MarshalIndent(result, "", "  ")
		writeMCPResult(w, req.ID, map[string]any{
			"content": []map[string]any{
				{"type": "text", "text": string(text)},
			},
		})

	default:
		writeMCPError(w, req.ID, -32601, "method not found: "+req.Method)
	}
}

// callTool 执行 MCP 工具（直查 Go Store——与 API 路由共享）。
func (s *Server) callTool(name string, args map[string]any) (any, error) {
	if s.Store == nil {
		return nil, fmt.Errorf("store not configured")
	}
	store := s.Store

	switch name {
	case "search_papers":
		query, _ := args["query"].(string)
		limit := 10
		if v, ok := args["limit"].(float64); ok {
			limit = int(v)
		}
		return store.SearchPapers(query, limit)

	case "get_paper":
		pid, _ := args["paper_id"].(string)
		return store.GetPaper(pid)

	case "get_research_question":
		qid, _ := args["question_id"].(string)
		return store.GetResearchQuestion(qid)

	case "list_claims":
		qid, _ := args["question_id"].(string)
		var statuses []string
		if arr, ok := args["statuses"].([]any); ok {
			for _, s := range arr {
				if str, ok := s.(string); ok {
					statuses = append(statuses, str)
				}
			}
		}
		return store.ListClaims(qid, statuses)

	case "get_claim_evidence":
		cid, _ := args["claim_id"].(string)
		return store.GetClaimEvidence(cid)

	case "get_research_diff":
		qid, _ := args["question_id"].(string)
		return store.GetResearchDiff(qid)

	case "list_jobs":
		limit := 20
		if v, ok := args["limit"].(float64); ok {
			limit = int(v)
		}
		return store.JobsList(limit)

	case "get_job":
		jid, _ := args["job_id"].(string)
		return store.JobGraph(jid)

	case "submit_task":
		capability, _ := args["capability"].(string)
		pid, _ := args["paper_id"].(string)
		if capability == "" || pid == "" {
			return nil, fmt.Errorf("capability and paper_id required")
		}
		jobID, taskID, created, err := store.SubmitCoreTask(capability,
			fmt.Sprintf(`{"paper_id":%q}`, pid), "", 1800)
		if err != nil {
			return nil, err
		}
		return map[string]any{
			"job_id": jobID, "task_id": taskID, "created": created,
		}, nil

	default:
		return nil, fmt.Errorf("unknown tool: %s", name)
	}
}

func writeMCPResult(w http.ResponseWriter, id any, result any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(MCPResponse{JSONRPC: "2.0", ID: id, Result: result})
}

func writeMCPError(w http.ResponseWriter, id any, code int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(MCPResponse{
		JSONRPC: "2.0", ID: id,
		Error: &MCPError{Code: code, Message: msg},
	})
}
