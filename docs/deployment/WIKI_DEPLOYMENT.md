# PaperMind 部署 Wiki

> 📚 **完整的部署指南** - 从本地开发到生产环境，一站式搞定！  
> 📅 最后更新：2026-03-02 | 版本：v3.1

---

## 📋 目录

- [快速开始](#快速开始)
- [架构概览](#架构概览)
- [部署方式](#部署方式)
  - [方式一：Docker 部署（生产推荐）](#方式一 docker 部署生产推荐)
  - [方式二：本地开发部署](#方式二本地开发部署)
  - [方式三：单容器部署](#方式三单容器部署旧版)
- [配置详解](#配置详解)
- [数据库管理](#数据库管理)
- [日常运维](#日常运维)
- [故障排查](#故障排查)
- [性能优化](#性能优化)
- [安全建议](#安全建议)

---

## 🚀 快速开始

### 系统要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| **CPU** | 2 核 | 4 核+ |
| **内存** | 4GB | 8GB+ |
| **磁盘** | 10GB | 50GB+ SSD |
| **Docker** | 20.10+ | 24.0+ |
| **Python** | 3.11+ | 3.11+ |
| **Node.js** | 18+ | 20+ |

### 5 分钟快速部署

```bash
# 1️⃣ 克隆项目
git clone https://github.com/Color2333/PaperMind.git && cd PaperMind

# 2️⃣ 配置环境变量
cp deploy/.env.example deploy/.env
vim deploy/.env  # 编辑配置，至少填写 LLM API Key 和 SMTP

# 3️⃣ 一键部署
chmod +x scripts/docker_deploy.sh
./scripts/docker_deploy.sh

# 4️⃣ 访问服务
# 🌐 前端：http://localhost:3002
# 📡 后端 API: http://localhost:8002
# 📚 API 文档：http://localhost:8002/docs
```

---

## 🏗️ 架构概览

### 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React 18)                      │
│  Port: 3002 (Docker) / 5173 (Dev)                           │
│         路由懒加载 · Vite 代码分割 · SSE 跨页保活            │
└─────────────────────────┬───────────────────────────────────┘
                          │ REST + SSE (JWT Auth)
┌─────────────────────────┴───────────────────────────────────┐
│                      FastAPI Backend                         │
│  Port: 8002 (Docker) / 8000 (Dev)                           │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│   Agent     │   Pipeline  │    RAG      │  Graph / Wiki /   │
│   Service   │   Engine    │   Service   │  Brief / Write    │
├─────────────┴─────────────┴─────────────┴───────────────────┤
│         Global TaskTracker (异步任务 + 实时进度)             │
├─────────────────────────────────────────────────────────────┤
│           Unified LLM Client (连接复用 + TTL 缓存)           │
│            OpenAI  │  Anthropic  │  ZhipuAI                 │
├─────────────────────────────────────────────────────────────┤
│   SQLite (WAL)  │  ArXiv API  │  Semantic Scholar API       │
└─────────────────────────────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │   APScheduler Worker    │
              │   按主题独立调度         │
              │   每日简报 / 每周图谱    │
              └─────────────────────────┘
```

### 服务组件

| 服务 | 端口 | 说明 | 技术栈 |
|------|------|------|--------|
| **前端** | 3002 | React 18 + Vite + TypeScript | React 18, Tailwind v4 |
| **后端 API** | 8002 | FastAPI REST API | FastAPI, SQLAlchemy |
| **Worker** | - | 定时任务 + 闲时处理 | APScheduler |
| **数据库** | - | SQLite (WAL 模式) | SQLite 3 |

### 目录结构

```
PaperMind/
├── apps/                    # 应用层
│   ├── api/                # FastAPI 路由和服务
│   ├── worker/             # Worker 进程
│   └── desktop/            # 桌面版（预留）
├── packages/               # 核心包
│   ├── domain/             # 领域模型和 schema
│   ├── storage/            # 数据库和仓储层
│   ├── integrations/       # 外部集成（LLM, Email 等）
│   └── ai/                 # AI 服务（RAG, Wiki 等）
├── infra/                  # 基础设施配置
│   ├── migrations/         # Alembic 数据库迁移
│   ├── nginx.conf          # Nginx 配置
│   └── supervisord.conf    # Supervisor 配置
├── frontend/               # 前端项目
│   ├── src/               # 源代码
│   ├── public/            # 静态资源
│   └── dist/              # 构建产物
├── deploy/                 # 部署配置
│   ├── .env               # 生产环境变量
│   └── .env.example       # 配置模板
├── scripts/                # 工具脚本
│   ├── docker_deploy.sh   # Docker 部署脚本
│   └── local_bootstrap.py # 本地初始化脚本
├── data/                   # 数据目录（运行时生成）
│   ├── papers/            # PDF 文件存储
│   └── briefs/            # 简报输出
└── logs/                   # 日志目录（运行时生成）
```

---

## 📦 部署方式

### 方式一：Docker 部署（生产推荐）

#### 优势

- ✅ **环境隔离** - 避免依赖冲突
- ✅ **一键部署** - 脚本自动化
- ✅ **易于运维** - 容器化管理
- ✅ **资源限制** - CPU/内存可控
- ✅ **持久化存储** - 数据卷保护

#### 部署步骤

**Step 1: 准备环境**

```bash
# 检查 Docker 版本
docker --version        # 应 >= 20.10
docker compose --version # 应 >= 2.0

# 如果未安装 Docker Compose
sudo apt-get install docker-compose-plugin  # Ubuntu/Debian
```

**Step 2: 配置环境变量**

```bash
# 复制配置模板
cp deploy/.env.example deploy/.env

# 编辑配置（必须填写！）
vim deploy/.env
```

**必填配置项：**

```env
# ==========================================
# LLM API Key（至少填写一个！）
# ==========================================
ZHIPU_API_KEY=your_zhipu_api_key_here  # 智谱 AI（推荐）
# OPENAI_API_KEY=sk-...                # OpenAI（可选）
# ANTHROPIC_API_KEY=sk-...             # Anthropic（可选）

# ==========================================
# SMTP 邮箱配置（必须填写！）
# ==========================================
SMTP_HOST=smtp.qq.com
SMTP_PORT=587
SMTP_USER=your_email@qq.com
SMTP_PASSWORD=your_smtp_auth_code  # 授权码，不是登录密码！
SMTP_FROM=your_email@qq.com
NOTIFY_DEFAULT_TO=receiver_email@qq.com

# ==========================================
# 成本管控（推荐开启！）
# ==========================================
COST_GUARD_ENABLED=true
PER_CALL_BUDGET_USD=0.05
DAILY_BUDGET_USD=2.0
```

**Step 3: 执行部署脚本**

```bash
# 赋予执行权限
chmod +x scripts/docker_deploy.sh

# 执行部署
./scripts/docker_deploy.sh
```

**Step 4: 验证部署**

```bash
# 查看容器状态
docker compose ps

# 预期输出：
# NAME                  STATUS              PORTS
# papermind-backend     Up (healthy)        0.0.0.0:8002->8000/tcp
# papermind-worker      Up (healthy)        
# papermind-frontend    Up (healthy)        0.0.0.0:3002->80/tcp

# 检查服务健康状态
curl http://localhost:8002/health
curl http://localhost:3002
```

#### 手动部署（不使用脚本）

```bash
# 1. 构建镜像
docker compose build

# 2. 启动服务
docker compose up -d

# 3. 查看日志
docker compose logs -f

# 4. 停止服务
docker compose down
```

#### 资源限制配置

`docker-compose.yml` 中已配置资源限制：

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2.0'    # CPU 限制 2 核
          memory: 2G     # 内存限制 2GB
        reservations:
          cpus: '0.5'    # 预留 0.5 核
          memory: 512M   # 预留 512MB
  
  worker:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
  
  frontend:
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
```

**总资源占用：** 4.5 核 CPU / 4.25GB 内存

---

### 方式二：本地开发部署

#### 优势

- ✅ **热重载** - 代码修改即时生效
- ✅ **调试方便** - 可使用 IDE 调试器
- ✅ **快速迭代** - 无需等待 Docker 构建

#### 部署步骤

**Step 1: 后端环境**

```bash
# 1. 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\Activate   # Windows

# 2. 安装依赖
pip install -e ".[llm,pdf]"

# 3. 复制环境变量
cp .env.example .env
vim .env  # 编辑配置

# 4. 初始化数据库
python scripts/local_bootstrap.py

# 5. 启动后端服务
uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000
```

**Step 2: 前端环境**

```bash
# 1. 进入前端目录
cd frontend

# 2. 安装依赖
npm install

# 3. 启动开发服务器
npm run dev

# 🌐 访问 http://localhost:5173
```

**Step 3: 配置代理（可选）**

`frontend/vite.config.ts` 已配置 API 代理：

```typescript
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

#### 开发工具推荐

```bash
# 后端 Lint
python -m ruff check .

# 后端格式化
python -m ruff format .

# 前端类型检查
cd frontend && npx tsc --noEmit

# 前端 Lint
cd frontend && npm run lint
```

---

### 方式三：单容器部署（旧版）

> ⚠️ **注意**：此方式已过时，推荐使用多容器分离部署

#### 特点

- 单个容器包含 Nginx + API + Worker
- 使用 Supervisor 管理多进程
- 适合资源受限环境

#### 部署步骤

```bash
# 1. 构建镜像
docker build -t papermind:latest .

# 2. 启动容器
docker run -d \
  --name papermind \
  -p 80:80 \
  -v papermind_data:/app/data \
  -v papermind_logs:/app/logs \
  --env-file deploy/.env \
  papermind:latest

# 3. 查看日志
docker logs -f papermind
```

---

## ⚙️ 配置详解

### 环境变量分类

#### 1. 基础配置

| 变量 | 说明 | 默认值 | 必填 |
|------|------|--------|------|
| `APP_ENV` | 运行环境 | `production` | ❌ |
| `API_HOST` | API 监听地址 | `0.0.0.0` | ❌ |
| `API_PORT` | API 端口 | `8000` | ❌ |
| `DATABASE_URL` | 数据库连接 | `sqlite:///./data/papermind.db` | ❌ |

#### 2. LLM 配置（核心！）

| 变量 | 说明 | 默认值 | 必填 |
|------|------|--------|------|
| `LLM_PROVIDER` | LLM 提供商 | `zhipu` | ✅ |
| `ZHIPU_API_KEY` | 智谱 API Key | - | ✅ |
| `OPENAI_API_KEY` | OpenAI API Key | - | ❌ |
| `ANTHROPIC_API_KEY` | Anthropic API Key | - | ❌ |
| `LLM_MODEL_SKIM` | 粗读模型 | `glm-4.7` | ❌ |
| `LLM_MODEL_DEEP` | 精读模型 | `glm-4.7` | ❌ |
| `LLM_MODEL_VISION` | 视觉模型 | `glm-4.6v` | ❌ |
| `EMBEDDING_MODEL` | 嵌入模型 | `embedding-3` | ❌ |

**Provider 说明：**

- `zhipu` - 智谱 AI（推荐，性价比高）
- `openai` - OpenAI（GPT-4 系列）
- `anthropic` - Anthropic（Claude 系列）

#### 3. SMTP 邮箱配置

| 变量 | 说明 | 示例 | 必填 |
|------|------|------|------|
| `SMTP_HOST` | SMTP 服务器 | `smtp.qq.com` | ✅ |
| `SMTP_PORT` | SMTP 端口 | `587` | ✅ |
| `SMTP_USER` | 发件人邮箱 | `user@qq.com` | ✅ |
| `SMTP_PASSWORD` | SMTP 授权码 | `xxx` | ✅ |
| `SMTP_FROM` | 发件人显示名 | `PaperMind` | ✅ |
| `NOTIFY_DEFAULT_TO` | 默认收件人 | `user@qq.com` | ✅ |

**常见邮箱 SMTP 配置：**

```env
# QQ 邮箱
SMTP_HOST=smtp.qq.com
SMTP_PORT=587
SMTP_USER=your_email@qq.com
SMTP_PASSWORD=your_auth_code  # 在邮箱设置中获取授权码

# 163 邮箱
SMTP_HOST=smtp.163.com
SMTP_PORT=587
SMTP_USER=your_email@163.com
SMTP_PASSWORD=your_auth_code

# Gmail
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password  # 应用专用密码
```

#### 4. 成本管控配置

| 变量 | 说明 | 默认值 | 推荐 |
|------|------|--------|------|
| `COST_GUARD_ENABLED` | 启用成本守卫 | `true` | ✅ |
| `PER_CALL_BUDGET_USD` | 单次调用预算 | `0.05` | ✅ |
| `DAILY_BUDGET_USD` | 每日预算 | `2.0` | ✅ |

#### 5. 调度配置（UTC 时间）

| 变量 | 说明 | 默认值 | 北京时间 |
|------|------|--------|---------|
| `DAILY_CRON` | 每日简报时间 | `0 4 * * *` | 12:00 |
| `WEEKLY_CRON` | 每周图谱维护 | `0 22 * * 0` | 周一 06:00 |
| `DEFAULT_MAX_DEEP_READS` | 每日精读数量 | `2` | ✅ |

#### 6. 站点认证配置

| 变量 | 说明 | 默认值 | 必填 |
|------|------|--------|------|
| `AUTH_PASSWORD` | 站点访问密码 | - | ❌ |
| `AUTH_SECRET_KEY` | JWT 密钥 | 自动生成 | ❌ |

**启用认证：**

```env
AUTH_PASSWORD=your_secure_password
AUTH_SECRET_KEY=your_random_secret_key_123456
```

---

### CORS 配置

```env
# 开发环境
CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Docker 环境
CORS_ALLOW_ORIGINS=http://localhost:3002,http://127.0.0.1:3002

# 生产环境（自定义域名）
CORS_ALLOW_ORIGINS=https://pm.vibingu.cn,http://pm.vibingu.cn
```

---

## 🗄️ 数据库管理

### 数据库初始化

**Docker 部署：** 自动初始化

**本地部署：** 手动执行

```bash
python scripts/local_bootstrap.py
```

### 数据库迁移（Alembic）

```bash
# 进入 infra 目录
cd infra

# 查看迁移历史
alembic history

# 创建新迁移
alembic revision --autogenerate -m "描述"

# 应用迁移
alembic upgrade head

# 回滚到上一个版本
alembic downgrade -1

# 回滚到指定版本
alembic downgrade <revision_id>
```

### 数据库备份

```bash
# 1. 停止服务
docker compose down

# 2. 备份数据卷
docker run --rm \
  -v papermind_data:/data \
  -v $(pwd):/backup \
  ubuntu tar czf /backup/papermind_$(date +%Y%m%d).tar.gz -C /data .

# 3. 重启服务
docker compose up -d
```

### 数据库恢复

```bash
# 1. 停止服务
docker compose down

# 2. 清空数据卷
docker volume rm papermind_data

# 3. 创建新数据卷
docker volume create papermind_data

# 4. 恢复备份
docker run --rm \
  -v papermind_data:/data \
  -v $(pwd):/backup \
  ubuntu tar xzf /backup/papermind_20260302.tar.gz -C /data

# 5. 重启服务
docker compose up -d
```

---

## 🔧 日常运维

### 查看服务状态

```bash
# 查看所有容器状态
docker compose ps

# 查看详细信息
docker compose top

# 查看资源使用
docker stats
```

### 查看日志

```bash
# 查看全部日志
docker compose logs -f

# 查看后端日志
docker compose logs -f backend

# 查看 Worker 日志
docker compose logs -f worker

# 查看前端日志
docker compose logs -f frontend

# 查看最近 100 行
docker compose logs --tail=100 backend
```

### 重启服务

```bash
# 重启全部服务
docker compose restart

# 重启单个服务
docker compose restart backend
docker compose restart worker
docker compose restart frontend
```

### 停止服务

```bash
# 停止全部服务
docker compose down

# ⚠️ 警告：停止并删除数据卷（会丢失数据！）
docker compose down -v
```

### 更新部署

```bash
# 1. 拉取最新代码
git pull

# 2. 重新构建并启动
docker compose up -d --build

# 3. 查看日志确认启动成功
docker compose logs -f
```

---

## ❓ 故障排查

### Q1: 容器启动失败？

```bash
# 查看容器日志
docker compose logs backend

# 检查配置文件
docker exec papermind-backend cat /app/.env

# 检查数据库初始化
docker exec papermind-backend ls -lh /app/data/

# 检查端口占用
lsof -i :8002
lsof -i :3002
```

### Q2: Worker 不执行任务？

```bash
# 检查 Worker 是否运行
docker compose ps worker

# 查看 Worker 日志
docker compose logs -f worker

# 检查心跳文件
docker exec papermind-worker cat /tmp/worker_heartbeat

# 重启 Worker
docker compose restart worker
```

### Q3: 邮件发送失败？

```bash
# 检查 SMTP 配置
docker exec papermind-backend env | grep SMTP

# 测试 SMTP 连接
docker exec papermind-backend python -c "
from packages.config import get_settings
s = get_settings()
print('SMTP_HOST:', s.smtp_host)
print('SMTP_USER:', s.smtp_user)
print('配置完整:', all([s.smtp_host, s.smtp_user, s.smtp_password]))
"

# 重启后端加载新配置
docker compose restart backend
```

### Q4: 端口冲突？

```bash
# 检查端口占用
lsof -i :3002
lsof -i :8002

# 修改 docker-compose.yml 端口映射
# 例如改为 3003 和 8003
ports:
  - "3003:80"   # 前端
  - "8003:8000" # 后端
```

### Q5: LLM 调用失败？

```bash
# 检查 API Key 配置
docker exec papermind-backend env | grep -E "ZHIPU|OPENAI|ANTHROPIC"

# 测试 LLM 连接
docker exec papermind-backend python -c "
from packages.integrations.llm_client import LLMClient
client = LLMClient()
result = client.summarize_text('测试', stage='test')
print('LLM 响应:', result.content)
"

# 查看 LLM 调用日志
docker compose logs backend | grep -i "llm\|api"
```

### Q6: 数据库锁死？

```bash
# 进入容器
docker exec -it papermind-backend bash

# 检查数据库文件
ls -lh /app/data/papermind.db

# 删除 WAL 文件（如果有）
rm -f /app/data/papermind.db-wal
rm -f /app/data/papermind.db-shm

# 重启服务
docker compose restart backend
```

---

## ⚡ 性能优化

### 1. 增加并发数

```env
# deploy/.env
IDLE_BATCH_SIZE=10      # 增加到 10 篇
IDLE_PROCESSOR_ENABLED=true
```

### 2. 调整精读配额

```env
# 如果费用充足，增加精读数量
DEFAULT_MAX_DEEP_READS=5  # 从 2 篇增加到 5 篇
```

### 3. 优化数据库性能

```yaml
# docker-compose.yml
backend:
  volumes:
    - pm_data:/app/data
    # 使用 SSD 存储
    - /ssd/papermind_data:/app/data
```

### 4. 调整资源限制

```yaml
# docker-compose.yml
backend:
  deploy:
    resources:
      limits:
        cpus: '4.0'    # 增加到 4 核
        memory: 4G     # 增加到 4GB
```

### 5. 启用 Redis 缓存（高级）

> 未来版本支持

---

## 🔐 安全建议

### 1. 防火墙配置

```bash
# 只允许本地访问（生产环境）
ufw allow from 127.0.0.1 to any port 3002
ufw allow from 127.0.0.1 to any port 8002

# 或允许特定 IP
ufw allow from 192.168.1.0/24 to any port 3002
ufw allow from 192.168.1.0/24 to any port 8002
```

### 2. HTTPS 配置（生产环境必需）

使用 Nginx 反向代理 + Let's Encrypt:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    location / {
        proxy_pass http://localhost:3002;
    }
    
    location /api/ {
        proxy_pass http://localhost:8002;
    }
}
```

**Let's Encrypt 证书申请：**

```bash
# 安装 Certbot
sudo apt-get install certbot python3-certbot-nginx

# 申请证书
sudo certbot --nginx -d your-domain.com

# 自动续期
sudo certbot renew --dry-run
```

### 3. 敏感配置保护

```bash
# 设置配置文件权限
chmod 600 deploy/.env

# 不要将 .env 提交到 Git
echo "deploy/.env" >> .gitignore

# 使用环境变量注入敏感信息
docker run -e ZHIPU_API_KEY=your_key ...
```

### 4. 数据库加密（可选）

> 未来版本支持 SQLCipher

---

## 📊 监控告警

### 健康检查端点

```bash
# 后端健康检查
curl http://localhost:8002/health

# Worker 心跳检查
docker exec papermind-worker cat /tmp/worker_heartbeat

# 前端健康检查
curl -I http://localhost:3002
```

### Prometheus + Grafana 监控（可选）

创建 `docker-compose.monitoring.yml`:

```yaml
version: '3.8'
services:
  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
  
  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin

volumes:
  grafana_data:
```

启动监控：

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

---

## 🎯 最佳实践

### 1. 定期备份

```bash
# 添加到 crontab（每天凌晨 2 点备份）
0 2 * * * cd /path/to/PaperMind && ./scripts/backup.sh
```

### 2. 日志轮转

```bash
# 创建 /etc/logrotate.d/papermind
/var/lib/docker/volumes/papermind_logs/_data/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### 3. 资源监控

```bash
# 使用 watch 命令实时监控
watch -n 1 'docker stats --no-stream'
```

### 4. 自动化部署

```bash
# 使用 GitHub Actions 自动部署
# .github/workflows/deploy.yml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Deploy
        run: ./scripts/docker_deploy.sh
```

---

## 📞 获取帮助

### 官方文档

- [GitHub 仓库](https://github.com/Color2333/PaperMind)
- [API 文档](http://localhost:8002/docs)
- [更新日志](CHANGELOG.md)

### 社区支持

- GitHub Issues - 问题反馈
- GitHub Discussions - 讨论交流

---

## 📝 更新记录

| 日期 | 版本 | 更新内容 |
|------|------|---------|
| 2026-03-02 | v1.0 | 初始版本，完善部署文档 |

---

**部署完成！享受全自动的论文追踪体验！** 🎉

> Built with ❤️ by [Color2333](https://github.com/Color2333)
