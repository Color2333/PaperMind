# PaperMind Pi LLM 网关 sidecar——运行 gateway/gateway.js（同步自
# PaperMind-Terminal/packages/papermind-cli/src/gateway.js）。
FROM node:22-alpine
WORKDIR /app
COPY package.json ./
# 大陆构建环境友好：默认 npm 源，慢时可换 registry.npmmirror.com
RUN npm install --omit=dev --no-audit --no-fund
COPY gateway.js ./
ENV NODE_ENV=production
CMD ["node", "gateway.js"]
