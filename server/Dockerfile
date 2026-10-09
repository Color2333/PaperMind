# PaperMind Go API（绞杀者入口 → Phase 7 终态唯一 API）
# Phase 4 起：agent chat 在 Go 侧 spawn pm（Pi 引擎）——镜像烘焙 Node 22 + pm_agent
# 注意：build context 是仓库根（compose 里 context: .，dockerfile: server/Dockerfile）
FROM golang:1.26-alpine AS build
# 大陆构建环境：Go 模块走国内代理
ENV GOPROXY=https://goproxy.cn,direct
WORKDIR /src
COPY server/go.mod server/go.sum ./
RUN go mod download
COPY server/ .
RUN CGO_ENABLED=0 go build -ldflags "-s -w" -o /out/papermind-api .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl xz-utils \
    && rm -rf /var/lib/apt/lists/*
# Node 22（pm 依赖 fs.globSync 等 Node≥22 API）—— npmmirror 二进制镜像（大陆可达）
RUN curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors \
    -o /tmp/node.tar.xz \
    https://registry.npmmirror.com/-/binary/node/v22.23.3/node-v22.23.3-linux-x64.tar.xz \
    && tar -xJf /tmp/node.tar.xz --strip-components=1 -C /usr/local \
    && rm /tmp/node.tar.xz \
    && node --version
COPY --from=build /out/papermind-api /usr/local/bin/papermind-api
# Pi agent 桥：Node 版 pm（webchat spawn `pm -p --json` 的执行体）
COPY pm_agent/ /opt/pm-agent/
RUN cd /opt/pm-agent \
    && npm install --omit=dev --registry=https://registry.npmmirror.com \
    && ln -sf /opt/pm-agent/bin/pm.js /usr/local/bin/pm \
    && pm --version | grep -q papermind/cli
RUN mkdir -p /app/data/papers /app/data/briefs
ENV PAPERMIND_AGENT_DIR=/data
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -sf http://localhost:8080/api/health || exit 1
ENTRYPOINT ["/usr/local/bin/papermind-api"]
