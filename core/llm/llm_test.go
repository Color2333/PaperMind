package llm

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCompleteStreaming(t *testing.T) {
	// mock OpenAI-compatible SSE server
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.Write([]byte("data: {\"choices\":[{\"delta\":{\"role\":\"assistant\",\"content\":\"你好\"}}]}\n\n"))
		w.Write([]byte("data: {\"choices\":[{\"delta\":{\"content\":\"，世界。\"},\"finish_reason\":null}]}\n\n"))
		w.Write([]byte("data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":5,\"total_tokens\":15}}\n\n"))
		w.Write([]byte("data: [DONE]\n\n"))
	}))
	defer srv.Close()

	client := NewClient()
	client.RegisterProvider(&Provider{
		Name: "test", BaseURL: srv.URL, APIKey: "key", Model: "mock-model",
	})

	resp, err := client.Complete("test", "", []Message{{Role: "user", Content: "hi"}}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if resp.Content != "你好，世界。" {
		t.Fatalf("content=%q", resp.Content)
	}
	if resp.InputTokens != 10 || resp.OutputTokens != 5 {
		t.Fatalf("tokens: in=%d out=%d", resp.InputTokens, resp.OutputTokens)
	}
	if resp.FinishReason != "stop" {
		t.Fatalf("finish=%s", resp.FinishReason)
	}
}

func TestCompleteWithToolCalls(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.Write([]byte(`data: {"choices":[{"delta":{"role":"assistant","tool_calls":[{"index":0,"id":"call-1","type":"function","function":{"name":"pm_search","arguments":"{\"query\":"}}]}}]}` + "\n\n"))
		w.Write([]byte(`data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"test\"}"}}]}}]}` + "\n\n"))
		w.Write([]byte(`data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}` + "\n\n"))
		w.Write([]byte("data: [DONE]\n\n"))
	}))
	defer srv.Close()

	client := NewClient()
	client.RegisterProvider(&Provider{Name: "test", BaseURL: srv.URL, APIKey: "k", Model: "m"})

	resp, err := client.Complete("test", "", []Message{{Role: "user", Content: "search"}}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(resp.ToolCalls) != 1 {
		t.Fatalf("tool_calls=%d", len(resp.ToolCalls))
	}
	tc := resp.ToolCalls[0]
	if tc.Function.Name != "pm_search" {
		t.Fatalf("name=%s", tc.Function.Name)
	}
	if tc.Function.Arguments != `{"query":"test"}` {
		t.Fatalf("arguments=%s", tc.Function.Arguments)
	}
	if resp.FinishReason != "tool_calls" {
		t.Fatalf("finish=%s", resp.FinishReason)
	}
}

func TestProviderRouting(t *testing.T) {
	client := NewClient()
	client.RegisterProvider(&Provider{Name: "xiaomi", BaseURL: "http://a", APIKey: "k", Model: "m1"})
	client.RegisterProvider(&Provider{Name: "zhipu", BaseURL: "http://b", APIKey: "k", Model: "m2"})

	p, err := client.GetProvider("zhipu")
	if err != nil || p.BaseURL != "http://b" {
		t.Fatalf("zhipu routing failed")
	}
	p, err = client.GetProvider("") // 默认
	if err != nil || p.Name != "xiaomi" {
		t.Fatalf("default routing failed")
	}
}
