# PaperMind Docker 部署指南 - 端口预留版

> 适用于已有项目占用 3001 和 8001 端口的场景
> 
> **端口规划**:
> - 现有项目：3001(前端) + 8001(后端)
> - PaperMind：**3002(前端) + 8002(后端)**

---

## 📋 目录

- [快速开始](#快速开始)
- [端口规划](#端口规划)
- [资源配置](#资源配置)
- [部署步骤](#部署步骤)
- [日常运维](#日常运维)
- [故障排查](#故障排查)

---

## 🚀 快速开始

### 1️⃣ 克隆项目

```bash
git clone <repo-url> && cd PaperMind
```

### 2️⃣ 配置环境变量

```bash
# 复制配置模板
cp deploy/.env.example deploy/.env

# 编辑配置（必须填写！）
vim deploy/.env
```

**必须填写的配置**:
```env
# LLM API Key（至少一个）
ZHIPU_API_KEY=your_api_key_here

# SMTP 邮箱（用于接收日报）
SMTP_USER=your_email@qq.com
SMTP_PASSWORD=your_smtp_auth_code  # 授权码！
NOTIFY_DEFAULT_TO=receiver_email@qq.com
```

### 3️⃣ 一键部署

```bash
# 执行部署脚本
chmod +x scripts/docker_deploy.sh
./scripts/docker_deploy.sh
```

### 4️⃣ 访问服务

- **前端**: http://localhost:3002
- **后端 API**: http://localhost:8002
- **API 文档**: http://localhost:8002/docs

---

## 🔌 端口规划

| 服务 | 容器内端口 | 宿主机端口 | 说明 |
|------|-----------|-----------|------|
| **前端** | 80 | **3002** | Nginx 托管静态文件 |
| **后端** | 8000 | **8002** | FastAPI API 服务 |
| **Worker** | - | - | 定时任务（无对外端口） |

### 端口冲突检测

```bash
# 检查 3002 端口是否被占用
lsof -i :3002

# 检查 8002 端口是否被占用
lsof -i :8002

# 如果被占用，修改 docker-compose.yml 中的端口映射
```

---

## 💾 资源配置

### 默认资源限制

| 服务 | CPU 限制 | 内存限制 | 说明 |
|------|---------|---------|------|
| **后端** | 2 核 | 2GB | API 服务 + LLM 调用 |
| **Worker** | 2 核 | 2GB | 定时任务 + 闲时处理 |
| **前端** | 0.5 核 | 256MB | Nginx 静态托管 |
| **总计** | 4.5 核 | 4.25GB | - |

### 调整资源配置

编辑 `docker-compose.yml`:

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '4.0'    # 增加到 4 核
          memory: 4G     # 增加到 4GB
```

---

## 📦 部署步骤

### 方法 1: 使用部署脚本（推荐）

```bash
./scripts/docker_deploy.sh
```

### 方法 2: 手动部署

```bash
# 1. 配置环境变量
cp deploy/.env.example deploy/.env
vim deploy/.env

# 2. 构建镜像
docker compose build

# 3. 启动服务
docker compose up -d

# 4. 查看状态
docker compose ps

# 5. 查看日志
docker compose logs -f
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

# 停止并删除数据卷（⚠️ 危险操作！）
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

## 📊 健康检查

### 检查后端健康

```bash
curl http://localhost:8002/health
```

预期输出：
```json
{"status": "ok", "timestamp": "..."}
```

### 检查 Worker 心跳

```bash
docker exec papermind-worker cat /tmp/worker_heartbeat
```

预期输出：Unix 时间戳（应该是最近的）

### 检查前端

```bash
curl -I http://localhost:3002
```

预期输出：`HTTP/1.1 200 OK`

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

### Q5: 数据丢失？

```bash
# 检查数据卷
docker volume ls | grep papermind

# 查看数据卷内容
docker volume inspect papermind_data

# 备份数据卷
docker run --rm -v papermind_data:/data -v $(pwd):/backup ubuntu tar czf /backup/papermind_backup.tar.gz -C /data .
```

---

## 🔐 安全建议

### 1️⃣ 防火墙配置

```bash
# 只允许本地访问（生产环境）
ufw allow from 127.0.0.1 to any port 3002
ufw allow from 127.0.0.1 to any port 8002

# 或允许特定 IP
ufw allow from 192.168.1.0/24 to any port 3002
ufw allow from 192.168.1.0/24 to any port 8002
```

### 2️⃣ HTTPS 配置（生产环境必需）

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

### 3️⃣ 敏感配置保护

```bash
# 设置配置文件权限
chmod 600 deploy/.env

# 不要将 .env 提交到 Git
echo "deploy/.env" >> .gitignore
```

---

## 📈 性能优化

### 1️⃣ 增加并发数

```env
# deploy/.env
IDLE_BATCH_SIZE=10      # 增加到 10 篇
IDLE_PROCESSOR_ENABLED=true
```

### 2️⃣ 调整精读配额

```env
# 如果费用充足，增加精读数量
DEFAULT_MAX_DEEP_READS=5  # 从 2 篇增加到 5 篇
```

### 3️⃣ 优化数据库性能

```yaml
# docker-compose.yml
backend:
  volumes:
    - pm_data:/app/data
    # 使用 SSD 存储
    - /ssd/papermind_data:/app/data
```

---

## 🎯 监控告警

### Prometheus + Grafana 监控

```yaml
# docker-compose.monitoring.yml
version: '3.8'
services:
  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
  
  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
```

### 日志聚合

```bash
# 使用 Loki + Promtail
docker compose -f docker-compose.yml -f docker-compose.loki.yml up -d
```

---

**部署完成！享受全自动的论文追踪体验！** 🎉
