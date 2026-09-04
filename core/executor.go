// Go Executor 循环（Phase 2）：claim → pipeline compute → proposal → apply-result。
// 与 Python Executor 同语义（claim → handler → complete），但全在 Go 进程内。
package core

import (
	"fmt"
	"log"
	"time"

	"github.com/Color2333/PaperMind/core/llm"
)

// GoExecutor 循环：从 CoreStore 领取任务并执行 A 档 proposal。
type GoExecutor struct {
	Store      *CoreStore
	Pipeline   *PipelineExecutor
	ExecutorID string
	stop       chan struct{}
	done       chan struct{}
}

// NewGoExecutor 创建 Go Executor。
func NewGoExecutor(store *CoreStore, llmClient *llm.Client, provider, executorID string) *GoExecutor {
	return &GoExecutor{
		Store:      store,
		Pipeline:   NewPipelineExecutor(llmClient, provider),
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
	case "skim_paper":
		title, _ := task.Input["title"].(string)
		abstract, _ := task.Input["abstract"].(string)
		if title == "" {
			// 从 DB 读论文 title/abstract
			paper, _ := e.Store.GetPaper(task.Input["paper_id"].(string))
			if paper != nil {
				title, _ = paper["title"].(string)
				abstract, _ = paper["abstract"].(string)
			}
		}
		proposal, computeErr = e.Pipeline.SkimProposal(
			task.Input["paper_id"].(string), title, abstract)

	case "deep_read_paper":
		pid, _ := task.Input["paper_id"].(string)
		title, _ := task.Input["title"].(string)
		sourceText := task.Input["source_text"].(string)
		if title == "" {
			paper, _ := e.Store.GetPaper(pid)
			if paper != nil {
				title, _ = paper["title"].(string)
			}
		}
		proposal, computeErr = e.Pipeline.DeepDiveProposal(pid, title, sourceText)

	case "embed_paper":
		pid, _ := task.Input["paper_id"].(string)
		title, _ := task.Input["title"].(string)
		abstract, _ := task.Input["abstract"].(string)
		if title == "" {
			paper, _ := e.Store.GetPaper(pid)
			if paper != nil {
				title, _ = paper["title"].(string)
				abstract, _ = paper["abstract"].(string)
			}
		}
		proposal, computeErr = e.Pipeline.EmbedProposal(pid, title, abstract)

	default:
		computeErr = fmt.Errorf("capability %s 无 Go executor handler", task.Capability)
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

func (e *GoExecutor) claimCapabilities() []string {
	return []string{"skim_paper", "deep_read_paper", "embed_paper"}
}
