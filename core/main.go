// Go Core 入口：默认监听 :8081（可用 CORE_ADDR 覆盖）。
package core

import (
	"log"
	"net/http"
	"os"
	"time"
)

// Run 启动 Core HTTP 服务（阻塞）。
func Run() {
	addr := os.Getenv("CORE_ADDR")
	if addr == "" {
		addr = ":8081"
	}
	server := &http.Server{
		Addr:              addr,
		Handler:           NewServer(NewRegistry()).Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}
	log.Printf("PaperMind Go Core (%s) listening on %s", CoreVersion, addr)
	log.Fatal(server.ListenAndServe())
}
