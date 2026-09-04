package core

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestMCPInitialize(t *testing.T) {
	s := newTestStore(t)
	server := NewServerWithStore(NewExecutorRegistry(), nil, s)
	req := httptest.NewRequest("POST", "/mcp", strings.NewReader(
		`{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}`))
	rec := httptest.NewRecorder()
	server.ServeMCP(rec, req)
	if rec.Code != 200 {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	var resp MCPResponse
	if err := json.NewDecoder(rec.Body).Decode(&resp); err != nil {
		t.Fatal(err)
	}
	result, _ := resp.Result.(map[string]any)
	if result["protocolVersion"] != "2024-11-05" {
		t.Fatalf("protocolVersion=%v", result["protocolVersion"])
	}
}

func TestMCPToolsList(t *testing.T) {
	s := newTestStore(t)
	server := NewServerWithStore(NewExecutorRegistry(), nil, s)
	req := httptest.NewRequest("POST", "/mcp", strings.NewReader(
		`{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}`))
	rec := httptest.NewRecorder()
	server.ServeMCP(rec, req)
	var resp MCPResponse
	if err := json.NewDecoder(rec.Body).Decode(&resp); err != nil {
		t.Fatal(err)
	}
	result, _ := resp.Result.(map[string]any)
	tools, _ := result["tools"].([]any)
	if len(tools) < 9 {
		t.Fatalf("tools=%d (expected ≥9)", len(tools))
	}
}

func TestMCPToolCallSearchPapers(t *testing.T) {
	s := newTestStore(t)
	server := NewServerWithStore(NewExecutorRegistry(), nil, s)
	req := httptest.NewRequest("POST", "/mcp", strings.NewReader(
		`{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_papers","arguments":{"query":"test"}}}`))
	rec := httptest.NewRecorder()
	server.ServeMCP(rec, req)
	var resp MCPResponse
	if err := json.NewDecoder(rec.Body).Decode(&resp); err != nil {
		t.Fatal(err)
	}
	if resp.Error != nil {
		t.Fatalf("MCP error: %v", resp.Error)
	}
	result, _ := resp.Result.(map[string]any)
	content, _ := result["content"].([]any)
	if len(content) == 0 {
		t.Fatal("content 为空")
	}
}

func TestMCPToolCallUnknownTool(t *testing.T) {
	s := newTestStore(t)
	server := NewServerWithStore(NewExecutorRegistry(), nil, s)
	req := httptest.NewRequest("POST", "/mcp", strings.NewReader(
		`{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"nonexistent","arguments":{}}}`))
	rec := httptest.NewRecorder()
	server.ServeMCP(rec, req)
	var resp MCPResponse
	if err := json.NewDecoder(rec.Body).Decode(&resp); err != nil {
		t.Fatal(err)
	}
	result, _ := resp.Result.(map[string]any)
	if result["isError"] != true {
		t.Fatalf("未知工具应返回 isError=true")
	}
}
