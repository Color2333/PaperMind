// GitHub OAuth + JWT 登录端点（Phase 1d）。
package core

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// AuthConfig 持有 JWT 密钥和 GitHub OAuth 配置。
type AuthConfig struct {
	SecretKey      string // JWT 签名密钥（与 Python auth_secret_key 共用）
	GitHubClientID string
	GitHubSecret   string
	SiteURL        string
	DemoTTLMinutes int // Demo 临时身份 TTL
	AuthPassword   string
}

// RegisterAuthRoutes 注册 auth 端点到 mux。
func (s *Server) RegisterAuthRoutes(cfg *AuthConfig) {
	s.mux.HandleFunc("POST /auth/login", s.handlePasswordLogin(cfg))
	s.mux.HandleFunc("GET /auth/github/login", s.handleGitHubLogin(cfg))
	s.mux.HandleFunc("GET /auth/github/callback", s.handleGitHubCallback(cfg))
	s.mux.HandleFunc("GET /auth/status", s.handleAuthStatus(cfg))
}

// handlePasswordLogin：密码登录（与 Python /auth/login 兼容）。
func (s *Server) handlePasswordLogin(cfg *AuthConfig) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Password string `json:"password"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeAPIJSON(w, map[string]any{"detail": "invalid request"})
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		if cfg.AuthPassword == "" || req.Password != cfg.AuthPassword {
			writeAPIJSON(w, map[string]any{"detail": "密码错误"})
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		token := s.createJWT(map[string]any{
			"sub":         "authenticated",
			"auth_method": "password",
		}, cfg, 24*7) // 7 天
		writeAPIJSON(w, map[string]any{
			"access_token": token,
			"token_type":   "bearer",
		})
	}
}

// handleGitHubLogin：重定向到 GitHub OAuth 授权页。
func (s *Server) handleGitHubLogin(cfg *AuthConfig) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if cfg.GitHubClientID == "" || cfg.GitHubSecret == "" {
			http.Error(w, "GitHub OAuth 未配置", http.StatusServiceUnavailable)
			return
		}
		siteURL := cfg.SiteURL
		if siteURL == "" {
			siteURL = "http://localhost:3002"
		}
		callbackURL := siteURL + "/auth/github/callback"
		authURL := fmt.Sprintf(
			"https://github.com/login/oauth/authorize?client_id=%s&redirect_uri=%s&scope=read:user",
			cfg.GitHubClientID,
			url.QueryEscape(callbackURL),
		)
		http.Redirect(w, r, authURL, http.StatusFound)
	}
}

// handleGitHubCallback：GitHub 回调 → token 交换 → 用户信息 → PaperMind JWT。
func (s *Server) handleGitHubCallback(cfg *AuthConfig) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if cfg.GitHubClientID == "" || cfg.GitHubSecret == "" {
			http.Error(w, "GitHub OAuth 未配置", http.StatusServiceUnavailable)
			return
		}
		code := r.URL.Query().Get("code")
		if code == "" {
			http.Error(w, "missing code", http.StatusBadRequest)
			return
		}

		// 1. 交换 access_token
		tokenReq := fmt.Sprintf(
			`{"client_id":%q,"client_secret":%q,"code":%q}`,
			cfg.GitHubClientID, cfg.GitHubSecret, code,
		)
		req, _ := http.NewRequest("POST", "https://github.com/login/oauth/access_token",
			strings.NewReader(tokenReq))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "application/json")

		client := &http.Client{Timeout: 15 * time.Second}
		resp, err := client.Do(req)
		if err != nil {
			http.Error(w, "GitHub token exchange failed", http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()

		var tokenResp struct {
			AccessToken string `json:"access_token"`
		}
		if err = json.NewDecoder(resp.Body).Decode(&tokenResp); err != nil || tokenResp.AccessToken == "" {
			http.Error(w, "GitHub token 交换失败", http.StatusUnauthorized)
			return
		}

		// 2. 获取用户信息
		userReq, _ := http.NewRequest("GET", "https://api.github.com/user", nil)
		userReq.Header.Set("Authorization", "Bearer "+tokenResp.AccessToken)
		userResp, err := client.Do(userReq)
		if err != nil {
			http.Error(w, "GitHub user fetch failed", http.StatusBadGateway)
			return
		}
		defer userResp.Body.Close()
		var userData struct {
			Login string `json:"login"`
		}
		if err = json.NewDecoder(userResp.Body).Decode(&userData); err != nil || userData.Login == "" {
			http.Error(w, "GitHub user info failed", http.StatusUnauthorized)
			return
		}

		// 3. 签发 PaperMind Demo JWT
		ttlMinutes := cfg.DemoTTLMinutes
		if ttlMinutes <= 0 {
			ttlMinutes = 120
		}
		token := s.createJWT(map[string]any{
			"sub":          "demo:" + userData.Login,
			"auth_method":  "demo_github",
			"github_login": userData.Login,
			"demo":         true,
		}, cfg, ttlMinutes/(24*60)+1) // 粗略天数（JWT exp 用秒）

		// 4. 重定向到前端
		siteURL := cfg.SiteURL
		if siteURL == "" {
			siteURL = "http://localhost:3002"
		}
		http.Redirect(w, r, siteURL+"/?demo_token="+token, http.StatusFound)
	}
}

// handleAuthStatus：auth 配置状态（与 Python /auth/status 兼容）。
func (s *Server) handleAuthStatus(cfg *AuthConfig) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeAPIJSON(w, map[string]any{
			"auth_enabled":         cfg.AuthPassword != "",
			"github_oauth_enabled": cfg.GitHubClientID != "",
			"demo_mode":            false,
		})
	}
}

// createJWT 签发 JWT（HS256，与 Python PyJWT 兼容）。
func (s *Server) createJWT(data map[string]any, cfg *AuthConfig, hours int) string {
	claims := jwt.MapClaims{}
	for k, v := range data {
		claims[k] = v
	}
	claims["exp"] = time.Now().Add(time.Duration(hours) * time.Hour).Unix()
	claims["iat"] = time.Now().Unix()

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, _ := token.SignedString([]byte(cfg.SecretKey))
	return tokenStr
}
