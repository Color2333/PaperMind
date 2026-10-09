// PaperMind Go Worker（Phase 3）：嵌入式任务执行器 + 调度器。
//
// 单二进制替代 Python worker 容器：claim/heartbeat/apply 全部同进程直调
// CoreStore（零 HTTP），编排器 submit-and-wait 层消失（scheduler 直接提交
// 叶子任务）。与 Python worker 经 CAS 领取安全共存，逐能力退役。
//
// 环境变量：
//
//	CORE_DB_PATH            权威库 DSN（PG 生产 / SQLite 本地）
//	WORKER_EXECUTOR_ID      执行器标识（默认 go-worker-1）
//	PAPERMIND_GATEWAY_URL   Pi 网关地址（默认 http://gateway:8765）
//	PAPERMIND_GATEWAY_TOKEN 网关令牌
//	EMBEDDING_API_KEY/_BASE_URL/_MODEL/_DIMENSIONS  embedding provider
//	PDF_STORAGE_ROOT        PDF 存储根（默认 /app/data/papers）
//	S2_API_KEY / IEEE_API_KEY  可选外部源密钥
package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	core "github.com/Color2333/PaperMind/core"
)

func main() {
	dsn := os.Getenv("CORE_DB_PATH")
	if dsn == "" {
		dsn = "papermind.db"
	}
	store, err := core.OpenCoreStore(dsn)
	if err != nil {
		log.Fatalf("open store: %v", err)
	}
	defer store.Close()

	executorID := os.Getenv("WORKER_EXECUTOR_ID")
	if executorID == "" {
		executorID = "go-worker-1"
	}
	pdfRoot := os.Getenv("PDF_STORAGE_ROOT")
	if pdfRoot == "" {
		pdfRoot = "/app/data/papers"
	}

	env := &core.HandlerEnv{
		Store:   store,
		Gateway: core.NewGatewayClient(),
		Embed:   core.NewEmbedClient(),
		Arxiv:   core.NewArxivClient(),
		Scholar: core.NewScholarClient(),
		PDFRoot: pdfRoot,
	}
	if env.Embed == nil {
		log.Printf("[worker] EMBEDDING_API_KEY 未配置——embed_paper 任务将失败（原 Python 伪向量已弃用）")
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	runner := core.NewRunner(store, env, executorID)
	registerHandlers(runner)

	scheduler := core.NewScheduler(store)
	log.Printf("[worker] started: executor=%s db=%s pdf_root=%s",
		executorID, core.DescribeDSN(dsn), pdfRoot)

	done := make(chan struct{})
	go func() {
		runner.Start(ctx)
		close(done)
	}()
	scheduler.Start(ctx)
	<-done
	log.Printf("[worker] stopped")
}

// registerHandlers 注册 Phase 3 v1 能力面（其余能力暂由 Python worker 承接）。
func registerHandlers(r *core.Runner) {
	r.Register("skim_paper", core.HandleSkimPaper)
	r.Register("deep_read_paper", core.HandleDeepReadPaper)
	r.Register("extract_claims", core.HandleExtractClaims)
	r.Register("embed_paper", core.HandleEmbedPaper)
	r.Register("download_source", core.HandleDownloadSource)
	r.Register("upsert_paper", core.HandleUpsertPaper)
	r.Register("fetch_topic_papers", core.HandleFetchTopicPapers)
	r.Register("ingest_arxiv_query", core.HandleIngestArxivQuery)
	r.Register("import_selected", core.HandleImportSelected)
	r.Register("ingest_ieee", core.HandleIngestIEEE)
	r.Register("import_references", core.HandleImportReferences)
	r.Register("cs_feed_fetch_category", core.HandleCsFeedFetchCategory)
	r.Register("cs_feed_dispatch", core.HandleCsFeedDispatch)
	r.Register("sync_citations_paper", core.HandleSyncCitationsPaper)
	r.Register("sync_citations_incremental", core.HandleSyncCitationsIncremental)
	r.Register("sync_citations_topic", core.HandleSyncCitationsTopic)
}
