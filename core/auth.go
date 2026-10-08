// JWT auth middleware（Phase 1d）：验证与 Python 侧同一 secret 签发的 JWT token。
package core

import (
	"context"
	"fmt"
	"net/http"
	"strings"

	"github.com/golang-jwt/jwt/v5"
)

// contextKey 用于在 request context 中存用户信息。
type contextKey string

const claimsKey contextKey = "claims"

// Claims 是 JWT payload 中 PaperMind 使用的字段。
type Claims struct {
	Sub         string `json:"sub"`
	AuthMethod  string `json:"auth_method"`
	GithubLogin string `json:"github_login,omitempty"`
	Demo        bool   `json:"demo,omitempty"`
	TokenID     string `json:"token_id,omitempty"`
	TokenType   string `json:"token_type,omitempty"`
	jwt.RegisteredClaims
}

// JWTAuthMiddleware 验证 Bearer token（与 Python create_access_token 同 secret 同算法）。
func JWTAuthMiddleware(next http.Handler, secretKey string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// 白名单路径
		path := r.URL.Path
		if isWhitelisted(path) {
			next.ServeHTTP(w, r)
			return
		}

		// OPTIONS preflight
		if r.Method == http.MethodOptions {
			next.ServeHTTP(w, r)
			return
		}

		// 提取 token
		tokenStr := extractBearerToken(r)
		if tokenStr == "" {
			w.WriteHeader(http.StatusUnauthorized)
			writeAPIJSON(w, map[string]any{"detail": "Not authenticated"})
			return
		}

		// 验证 JWT
		claims := &Claims{}
		token, err := jwt.ParseWithClaims(tokenStr, claims, func(t *jwt.Token) (any, error) {
			if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
				alg, _ := t.Header["alg"].(string)
				return nil, fmt.Errorf("unexpected signing method: %v", alg)
			}
			return []byte(secretKey), nil
		})
		if err != nil || !token.Valid {
			w.WriteHeader(http.StatusUnauthorized)
			writeAPIJSON(w, map[string]any{"detail": "Invalid or expired token"})
			return
		}

		// 将 claims 存入 context
		ctx := context.WithValue(r.Context(), claimsKey, claims)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// GetClaims 从 request context 提取 JWT claims。
func GetClaims(ctx context.Context) *Claims {
	if claims, ok := ctx.Value(claimsKey).(*Claims); ok {
		return claims
	}
	return nil
}

var whitelistedPaths = map[string]bool{
	"/health":               true,
	"/readyz":               true,
	"/auth/login":           true,
	"/auth/status":          true,
	"/auth/device/start":    true,
	"/auth/device/poll":     true,
	"/auth/github/login":    true,
	"/auth/github/callback": true,
}

func isWhitelisted(path string) bool {
	if whitelistedPaths[path] {
		return true
	}
	// /mcp 前缀全部放行
	return strings.HasPrefix(path, "/mcp")
}

func extractBearerToken(r *http.Request) string {
	auth := r.Header.Get("Authorization")
	if strings.HasPrefix(auth, "Bearer ") {
		return strings.TrimPrefix(auth, "Bearer ")
	}
	// query param token（用于 PDF/图片等浏览器直接请求）
	return r.URL.Query().Get("token")
}
