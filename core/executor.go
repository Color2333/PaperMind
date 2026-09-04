// Go Executor 循环：claim → 无 LLM 纯计算 → proposal → apply-result 单事务。
// LLM 类能力（skim/deep_read/embed/extract_claims）由 Python Executor（AI 栈）领取，
// LLM 网关统一走 Pi（packages/ai）——Go 侧不复刻 provider 协议。
package core

import (
	"fmt"
	"log"
	"time"
)

// GoExecutor 循环：从 CoreStore 领取任务并执行 proposal。
type GoExecutor struct {
	Store      *CoreStore
	Pipeline   *PipelineExecutor
	ExecutorID string
	stop       chan struct{}
	done       chan struct{}
}

// NewGoExecutor 创建 Go Executor。
func NewGoExecutor(store *CoreStore, executorID string) *GoExecutor {
	return &GoExecutor{
		Store:      store,
		Pipeline:   NewPipelineExecutor(),
		ExecutorID: executorID,
		stop:       make(chan struct{}),
		done:       make(chan struct{}),
	}
}

// Start 启动 claim 循环（非阻塞）。
func (e *GoExecutor) Start() {
	go e.run()
}

// Stop 停止循环（drain 语义：等当前 attempt 收敛）。
func (e *GoExecutor) Stop() {
	close(e.stop)
	<-e.done
}

func (e *GoExecutor) run() {
	defer close(e.done)
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-e.stop:
			log.Printf("[go-executor] %s stopped", e.ExecutorID)
			return
		case <-ticker.C:
			e.pollOnce()
		}
	}
}

func (e *GoExecutor) pollOnce() {
	task, err := e.Store.ClaimTask(e.ExecutorID, e.claimCapabilities())
	if err != nil {
		log.Printf("[go-executor] claim error: %v", err)
		return
	}
	if task == nil {
		return // 无任务
	}

	var proposal map[string]any
	var computeErr error

	switch task.Capability {
	case "upsert_paper":
		arxivID, _ := task.Input["arxiv_id"].(string)
		title, _ := task.Input["title"].(string)
		abstract, _ := task.Input["abstract"].(string)
		proposal, computeErr = e.Pipeline.UpsertProposal(arxivID, title, abstract)

	case "download_source":
		arxivID, _ := task.Input["arxiv_id"].(string)
		proposal, computeErr = e.Pipeline.DownloadProposal(arxivID)

	case "fetch_feed":
		query, _ := task.Input["query"].(string)
		maxResults := 20
		if v, ok := task.Input["max_results"].(float64); ok {
			maxResults = int(v)
		}
		proposal, computeErr = e.Pipeline.FetchProposal(query, maxResults)

	default:
		computeErr = fmt.Errorf("capability %s 无 Go executor handler（LLM 类能力归 Python Executor）", task.Capability)
	}

	if computeErr != nil {
		log.Printf("[go-executor] task %s compute error: %v", task.TaskID[:8], computeErr)
		e.Store.FailTask(task.TaskID, e.ExecutorID, task.LeaseToken,
			"ComputeError", computeErr.Error())
		return
	}

	// apply-result 单事务
	status, err := e.Store.ApplyResult(task.TaskID, e.ExecutorID, task.LeaseToken, proposal)
	if err != nil {
		log.Printf("[go-executor] task %s apply error: %v", task.TaskID[:8], err)
		return
	}
	log.Printf("[go-executor] task %s → %s", task.TaskID[:8], status)
}

// claimCapabilities：仅无 LLM 的 A 档能力（LLM 类统一回流 Python Executor）。
func (e *GoExecutor) claimCapabilities() []string {
	return []string{"upsert_paper", "download_source", "fetch_feed"}
}
