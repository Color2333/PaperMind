package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
)

type Config struct {
	DatabaseURL   string // PG DSN（与 backend 同库）
	BackendOrigin string // Python backend（未移植路由的反代目标）
	AuthPassword  string // 站点密码（与 Python AUTH_PASSWORD 同值；空 = 关闭认证）
	SecretKey     string // JWT HS256 密钥（与 Python auth_secret_key 同值）
	SiteURL       string
	ListenAddr    string
}

func LoadConfig() Config {
	return Config{
		DatabaseURL:   envOr("DATABASE_URL", "postgresql://papermind:papermind@postgres:5432/papermind?sslmode=disable"),
		BackendOrigin: envOr("BACKEND_ORIGIN", "http://backend:8000"),
		AuthPassword:  os.Getenv("AUTH_PASSWORD"),
		SecretKey:     os.Getenv("AUTH_SECRET_KEY"),
		SiteURL:       envOr("SITE_URL", "http://localhost:3002"),
		ListenAddr:    envOr("LISTEN_ADDR", ":8080"),
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// proxyLegacy：未移植 /api/* 路由的透明反代（SSE 友好：立即 Flush）。
func (s *Server) proxyLegacy(w http.ResponseWriter, r *http.Request) {
	target, err := url.Parse(s.cfg.BackendOrigin)
	if err != nil {
		http.Error(w, "bad backend origin", http.StatusInternalServerError)
		return
	}
	proxy := &httputil.ReverseProxy{
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(target)
			pr.Out.Host = target.Host
			pr.Out.Header.Set("X-Served-By", "goserver-proxy")
		},
		FlushInterval: -1, // SSE 立即冲刷
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, e error) {
			log.Printf("proxy %s %s: %v", r.Method, r.URL.Path, e)
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadGateway)
			_, _ = w.Write([]byte(`{"detail":"backend unavailable"}`))
		},
	}
	proxy.ServeHTTP(w, r)
}
