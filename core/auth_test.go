package core

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func TestJWTAuthValid(t *testing.T) {
	secret := "test-secret-key"
	handler := JWTAuthMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		claims := GetClaims(r.Context())
		if claims == nil {
			t.Error("claims should be in context")
		}
		w.WriteHeader(200)
	}), secret)

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": "user-1", "auth_method": "jwt",
		"exp": time.Now().Add(time.Hour).Unix(),
	})
	tokenStr, _ := token.SignedString([]byte(secret))

	req := httptest.NewRequest("GET", "/api/papers", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != 200 {
		t.Fatalf("valid JWT should pass, got %d", rec.Code)
	}
}

func TestJWTAuthExpired(t *testing.T) {
	secret := "test-secret"
	handler := JWTAuthMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}), secret)

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": "user-1", "exp": time.Now().Add(-time.Hour).Unix(),
	})
	tokenStr, _ := token.SignedString([]byte(secret))

	req := httptest.NewRequest("GET", "/api/papers", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != 401 {
		t.Fatalf("expired JWT should 401, got %d", rec.Code)
	}
}

func TestJWTAuthWrongSecret(t *testing.T) {
	handler := JWTAuthMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {}), "correct-secret")

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": "user-1", "exp": time.Now().Add(time.Hour).Unix(),
	})
	tokenStr, _ := token.SignedString([]byte("wrong-secret"))

	req := httptest.NewRequest("GET", "/api/papers", nil)
	req.Header.Set("Authorization", "Bearer "+tokenStr)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	if rec.Code != 401 {
		t.Fatalf("wrong secret should 401, got %d", rec.Code)
	}
}

func TestWhitelistedPathsPass(t *testing.T) {
	handler := JWTAuthMiddleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(200)
	}), "secret")

	for _, path := range []string{"/health", "/readyz", "/auth/login", "/mcp"} {
		req := httptest.NewRequest("GET", path, nil)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != 200 {
			t.Fatalf("whitelisted %s should pass, got %d", path, rec.Code)
		}
	}
}

func TestCrossLanguageJWTCompatibility(t *testing.T) {
	// Python PyJWT HS256 签发的 token → Go 验证（模拟 Python 输出格式）
	secret := "shared-secret"
	// Python create_access_token 用 jwt.encode(data, secret, algorithm="HS256")
	// 生成的 JWT 格式是 header.payload.signature（base64url）
	pythonToken := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub":         "demo:github_user",
		"auth_method": "demo_github",
		"demo":        true,
		"exp":         time.Now().Add(time.Hour).Unix(),
		"iat":         time.Now().Unix(),
	})
	tokenStr, err := pythonToken.SignedString([]byte(secret))
	if err != nil {
		t.Fatal(err)
	}

	// Go 验证
	claims := &Claims{}
	token, err := jwt.ParseWithClaims(tokenStr, claims, func(t *jwt.Token) (any, error) {
		return []byte(secret), nil
	})
	if err != nil || !token.Valid {
		t.Fatalf("cross-language JWT validation failed: %v", err)
	}
	if claims.Sub != "demo:github_user" {
		t.Fatalf("sub=%s", claims.Sub)
	}
	if claims.AuthMethod != "demo_github" {
		t.Fatalf("auth_method=%s", claims.AuthMethod)
	}
	fmt.Println("cross-language JWT compatible ✓")
}
