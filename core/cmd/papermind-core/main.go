// PaperMind Go Core 入口（P1 修复：独立 main package）。
//
// 默认绑定 127.0.0.1:8081（P1 修复：不暴露到所有网卡）。
// 生产部署通过反向代理（HTTPS）暴露；CORE_ADDR 可覆盖。
package main

import (
	"log"
	"net/http"
	"os"
	"time"

	"github.com/Color2333/PaperMind/core"
)

func main() {
	addr := os.Getenv("CORE_ADDR")
	if addr == "" {
		addr = "127.0.0.1:8081" // P1 修复：默认 loopback，不绑 0.0.0.0
	}
	// P1 修复：可选静态 token 校验
	token := os.Getenv("CORE_TOKEN")

	registry := core.NewRegistry()
	server := core.NewServer(registry)

	var handler http.Handler = server.Handler()
	if token != "" {
		handler = core.TokenAuthMiddleware(handler, token)
	}

	srv := &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: 10 * time.Second,
	}
	log.Printf("PaperMind Go Core (%s) listening on %s", core.CoreVersion, addr)
	log.Fatal(srv.ListenAndServe())
}
