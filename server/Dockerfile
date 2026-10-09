# PaperMind Go API（2.1 重写 Phase 0：绞杀者入口）
# 已移植：设备码授权全流程 / 健康检查 / folder-stats；未移植 /api/* 反代 backend
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags "-s -w" -o /out/papermind-api .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates curl
COPY --from=build /out/papermind-api /usr/local/bin/papermind-api
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:8080/api/health || exit 1
ENTRYPOINT ["/usr/local/bin/papermind-api"]
