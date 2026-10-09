// Go Worker Runner：嵌入式任务执行器（Phase 3）。
//
// 与 Python Executor 宿主的本质区别：claim / heartbeat / apply 全部是
// CoreStore 同进程方法调用（零 HTTP 往返）；编排器 submit-and-wait 层整体
// 消失（scheduler 直接提交叶子任务，无 orchestration 池、无自死锁问题）。
//
// 资源类别隔离沿用 Python 注册表语义（default/network/llm/embedding），
// 用带容量信号量实现：LLM 长任务占线时不饿死轻网络任务。
package core

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"
)

// HandlerFunc 任务处理器：纯计算 → 返回 result（含 proposal），由 runner
// 经 ApplyResult 单事务落库。ctx 在 lease 丢失 / 协作取消 / 超时置位。
type HandlerFunc func(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error)

// HandlerEnv 处理器共享依赖（客户端连接复用，一次构建全 runner 共享）。
type HandlerEnv struct {
	Store   *CoreStore
	Gateway *GatewayClient
	Embed   *EmbedClient
	Arxiv   *ArxivClient
	Scholar *ScholarClient
	SMTP    *SMTPConfig
	PDFRoot string
}

// Runner 任务执行器。
type Runner struct {
	store      *CoreStore
	env        *HandlerEnv
	executorID string

	handlers map[string]HandlerFunc
	classes  map[string]*classPool
}

// classPool 单资源类别：能力集合 + 并发信号量。
type classPool struct {
	capabilities []string
	sem          chan struct{}
}

// Task 与 protocol.go 的执行器协议结构一致（ClaimTask 返回）——定义见 protocol.go。

// 并发度环境变量名 → 默认值（与 Python worker 的双池语义对齐，但池更细）。
var classConcurrencyDefaults = map[string]int{
	"llm":       2,
	"embedding": 2,
	"network":   4,
	"default":   4,
}

// classCapabilities 各资源类别的领取能力集合（Phase 3.5 全量执行面）。
var classCapabilities = map[string][]string{
	"llm":       {"skim_paper", "deep_read_paper", "extract_claims", "topic_wiki_save", "daily_brief_publish", "analyze_figures", "translate_bilingual_pdf"},
	"embedding": {"embed_paper"},
	"network": {
		"download_source", "ingest_arxiv_query", "import_selected", "ingest_ieee",
		"import_references", "cs_feed_fetch_category", "cs_feed_dispatch",
		"sync_citations_paper", "sync_citations_incremental", "sync_citations_topic",
		"fetch_topic_papers", "send_brief_email",
		"batch_process_unread", "skim_papers_batch", "weekly_graph_maintenance",
		"daily_ingest_and_brief", "daily_report_workflow", "daily_report_send_only",
	},
	"default": {"upsert_paper"},
}

// NewRunner 构建 runner（env 客户端由调用方按环境配置注入）。
func NewRunner(store *CoreStore, env *HandlerEnv, executorID string) *Runner {
	return &Runner{
		store:      store,
		env:        env,
		executorID: executorID,
		handlers:   map[string]HandlerFunc{},
		classes:    map[string]*classPool{},
	}
}

// Register 注册能力处理器（必须属于某个资源类别）。
func (r *Runner) Register(capability string, fn HandlerFunc) {
	r.handlers[capability] = fn
}

// Start 启动各资源类别 poll goroutine；阻塞至 ctx 取消。
func (r *Runner) Start(ctx context.Context) {
	for class, caps := range classCapabilities {
		conc := classConcurrencyDefaults[class]
		pool := &classPool{capabilities: caps, sem: make(chan struct{}, conc)}
		r.classes[class] = pool
		go r.pollLoop(ctx, pool)
	}
	<-ctx.Done()
}

// pollLoop 单类别领取循环：有空位就尝试 claim；claimed task 起独立 goroutine。
// 空队列 / 满载 / claim 出错都只等到下个 tick，不退出循环（此前 return 会让
// poll goroutine 永久死亡——首个任务失败重入队后无人再领取）。
func (r *Runner) pollLoop(ctx context.Context, pool *classPool) {
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
pollLoop:
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		for {
			select {
			case pool.sem <- struct{}{}:
			default:
				continue pollLoop // 该类别满载
			}
			task, err := r.store.ClaimTask(r.executorID, pool.capabilities)
			if err != nil {
				<-pool.sem
				log.Printf("[runner] claim error: %v", err)
				continue pollLoop
			}
			if task == nil {
				<-pool.sem
				continue pollLoop // 队列空 / 暂停
			}
			go r.runTask(ctx, task, pool)
		}
	}
}

// runTask 执行单个任务：心跳续约 + 协作取消探测 + handler + apply/fail。
func (r *Runner) runTask(ctx context.Context, task *Task, pool *classPool) {
	defer func() { <-pool.sem }()

	handler := r.handlers[task.Capability]
	if handler == nil {
		// 未注册能力被 claim 到（配置不一致）——立即失败归还，不占位
		_, _ = r.store.FailTask(task.TaskID, r.executorID, task.LeaseToken,
			"no_handler", "capability "+task.Capability+" 在 Go runner 未注册")
		return
	}

	// 任务级 ctx：timeout / 协作取消 / 进程退出
	timeoutS := task.TimeoutS
	if timeoutS <= 0 {
		timeoutS = 1800
	}
	taskCtx, cancel := context.WithTimeout(ctx, time.Duration(timeoutS)*time.Second)
	defer cancel()
	cancelRequested := false
	stopHeartbeat := make(chan struct{})
	var hbWG sync.WaitGroup
	hbWG.Add(1)
	go func() {
		defer hbWG.Done()
		// 续约节奏：lease 的 1/3（Python 同语义），至少 30s
		interval := time.Duration(task.TimeoutS) * time.Second / 3
		if interval < 30*time.Second {
			interval = 30 * time.Second
		}
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-stopHeartbeat:
				return
			case <-ticker.C:
				ok, wantCancel, err := r.store.HeartbeatTask(task.TaskID, r.executorID, task.LeaseToken)
				if err != nil {
					log.Printf("[runner] heartbeat %s error: %v", task.TaskID[:8], err)
					continue
				}
				if wantCancel {
					cancelRequested = true
					cancel()
					return
				}
				if !ok {
					// lease 丢失（被 reclaim）——安全点退出
					cancel()
					return
				}
			}
		}
	}()

	result, err := func() (res map[string]any, herr error) {
		defer func() {
			if rec := recover(); rec != nil {
				herr = fmt.Errorf("handler panic: %v", rec)
			}
		}()
		return handler(taskCtx, r.env, task)
	}()
	close(stopHeartbeat)
	hbWG.Wait()

	if err != nil {
		// 协作取消：回执 CancelExecution（终态 cancelled）
		if cancelRequested || ctx.Err() != nil {
			if _, cerr := r.store.CancelExecution(task.TaskID, r.executorID, task.LeaseToken); cerr != nil {
				log.Printf("[runner] cancel-execution %s rejected: %v", task.TaskID[:8], cerr)
			}
			log.Printf("[runner] task %s (%s) cancelled at safe point", task.TaskID[:8], task.Capability)
			return
		}
		_, ferr := r.store.FailTask(task.TaskID, r.executorID, task.LeaseToken, "handler_error", err.Error())
		if ferr != nil {
			log.Printf("[runner] fail-task %s error: %v", task.TaskID[:8], ferr)
		}
		log.Printf("[runner] task %s (%s) failed: %s", task.TaskID[:8], task.Capability, truncateStr(err.Error(), 200))
		return
	}

	status, aerr := r.store.ApplyResult(task.TaskID, r.executorID, task.LeaseToken, result)
	if aerr != nil {
		log.Printf("[runner] apply %s (%s) error: %v", task.TaskID[:8], task.Capability, aerr)
		return
	}
	log.Printf("[runner] task %s (%s) -> %s", task.TaskID[:8], task.Capability, status)
}

func truncateStr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
