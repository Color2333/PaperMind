package main

// jwt.go：HS256 JWT 校验（与 python-jose 签发的 Web 会话令牌逐字节兼容）。

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

type parsedJWT struct {
	claims jwt.MapClaims
	valid  bool
}

func jwtParseHS256(token, secret string) (parsedJWT, error) {
	parsed := parsedJWT{}
	claims := jwt.MapClaims{}
	parser := jwt.NewParser(
		jwt.WithValidMethods([]string{"HS256"}),
		jwt.WithExpirationRequired(),
	)
	_, err := parser.ParseWithClaims(token, claims, func(t *jwt.Token) (any, error) {
		return []byte(secret), nil
	})
	if err != nil {
		return parsed, err
	}
	exp, err := claims.GetExpirationTime()
	if err != nil {
		return parsed, err
	}
	if exp == nil || !exp.Time.After(time.Now().UTC()) {
		return parsed, errors.New("token is expired")
	}
	parsed.claims = claims
	parsed.valid = true
	return parsed, nil
}
