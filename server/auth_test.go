package main

// auth 单元测试：与 Python packages/auth.py 逐契约对齐的哈希/格式兼容性。

import (
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func TestHashTokenMatchesPythonSHA256(t *testing.T) {
	// Python: sha256("abc").hexdigest() = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
	if got := hashToken("abc"); got != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" {
		t.Fatalf("hash_token 与 Python SHA-256 不兼容: %s", got)
	}
}

func TestGenerateDeviceCodeFormat(t *testing.T) {
	raw, hash := generateDeviceCode()
	if len(raw) < 32 {
		t.Fatalf("device_code 长度不足: %d", len(raw))
	}
	if hash != hashToken(raw) {
		t.Fatal("hash 与 raw 不对应")
	}
}

func TestGenerateUserCodeFormat(t *testing.T) {
	code := generateUserCode()
	if len(code) != 9 || code[4] != '-' {
		t.Fatalf("user_code 格式错误: %s", code)
	}
	const alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
	for _, c := range code {
		if c == '-' {
			continue
		}
		if !strings.ContainsRune(alphabet, c) {
			t.Fatalf("user_code 含混淆字符: %c", c)
		}
	}
}

func TestJWTParsePythonJoseCompat(t *testing.T) {
	// python-jose HS256 签发（exp 为 NumericDate epoch 秒）——Go 侧必须可验
	const secret = "test-secret"
	// python: jwt.encode({"sub":"u1","exp": 9999999999}, secret, algorithm="HS256")
	pythonToken := "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1MSIsImV4cCI6OTk5OTk5OTk5OX0.eson7xKtNGMTgCTN9HuQDjU0-Yigsj8H3i5nkl2-3Og"
	parsed, err := jwtParseHS256(pythonToken, secret)
	if err != nil {
		t.Fatalf("python-jose 令牌校验失败: %v", err)
	}
	if !parsed.valid {
		t.Fatal("valid 应为 true")
	}

	// 过期令牌必须拒绝
	expired := "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1MSIsImV4cCI6MX0.7GXdivOsfXYWCPmkEKpbGijOmX5BjYMnNexCuF3n1Qs"
	if _, err = jwtParseHS256(expired, secret); err == nil {
		t.Fatal("过期令牌应被拒绝")
	}

	// 错误密钥必须拒绝
	if _, err = jwtParseHS256(pythonToken, "wrong"); err == nil {
		t.Fatal("错误密钥应被拒绝")
	}
}

func TestJwtExpiryCheck(t *testing.T) {
	claims := jwt.MapClaims{"exp": float64(time.Now().Add(-time.Hour).Unix())}
	exp, _ := claims.GetExpirationTime()
	if exp == nil || !exp.Time.Before(time.Now().UTC()) {
		t.Fatal("过期时间解析错误")
	}
}
