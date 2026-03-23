# IEEE 渠道集成 - MVP 部署指南

**版本**: v1.0-MVP  
**创建时间**: 2026-03-03  
**作者**: 老白 (Color2333)  
**状态**: ✅ MVP 开发完成，待部署测试

---

## 📦 MVP 阶段交付清单

### ✅ 已完成的功能

| 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|
| **IEEE 客户端** | `packages/integrations/ieee_client.py` | ✅ 完成 | IEEE API 封装，支持关键词搜索、DOI 查询 |
| **数据模型** | `packages/domain/schemas.py` | ✅ 完成 | `PaperCreate` 扩展支持多渠道 |
| **Pipeline 接口** | `packages/ai/pipelines.py` | ✅ 完成 | `ingest_ieee()` 方法 |
| **数据仓库** | `packages/storage/repositories.py` | ✅ 完成 | `list_existing_dois()` 去重方法 |
| **数据库迁移** | `infra/migrations/versions/20260303_0009_ieee_mvp.py` | ✅ 完成 | 添加 `source`/`source_id`/`doi` 字段 |
| **API 路由** | `apps/api/routers/papers.py` | ✅ 完成 | `/papers/ingest/ieee` 端点 |

### 📋 待完成的测试

- [ ] IEEE 客户端单元测试
- [ ] 本地 IEEE 摄取完整流程测试
- [ ] 后端编译和类型检查
- [ ] 数据库迁移测试

---

## 🚀 部署步骤

### 步骤 1: 配置环境变量

在 `.env` 文件中添加 IEEE 配置：

```bash
# .env

# ========== IEEE Xplore API 配置 ==========
# 获取 IEEE API Key: https://developer.ieee.org/
IEEE_API_ENABLED=false  # MVP 阶段默认关闭，测试时改为 true
IEEE_API_KEY=your_ieee_api_key_here  # 替换为你的 IEEE API Key
IEEE_DAILY_QUOTA_DEFAULT=10  # 默认每日 IEEE API 限额（免费 50 次/天）
IEEE_PDF_DOWNLOAD_ENABLED=false  # 暂不支持 PDF 下载
```

**⚠️ 重要提示:**
- IEEE API Key 需要到 https://developer.ieee.org/ 申请
- 免费版限制：50 次 API 调用/天
- 付费版：$129/月（500 次/天）

### 步骤 2: 运行数据库迁移

```bash
# 激活虚拟环境
source .venv/bin/activate

# 进入 infra 目录
cd infra

# 查看当前迁移状态
alembic current

# 执行 IEEE 迁移
alembic upgrade head

# 验证迁移成功
alembic current
# 应该显示：20260303_0009_ieee_mvp (head)
```

**验证迁移成功:**
```sql
-- 使用 SQLite 客户端检查字段
sqlite3 data/papermind.db

-- 查看 papers 表结构
.schema papers

-- 应该看到新增的字段:
-- source VARCHAR(32) DEFAULT 'arxiv' NOT NULL
-- source_id VARCHAR(128)
-- doi VARCHAR(128)
```

### 步骤 3: 安装依赖（如果有新增）

```bash
# 重新安装项目依赖（确保新模块被识别）
pip install -e ".[llm,pdf]"

# 或者使用 pnpm（如果是 monorepo）
pnpm install
```

### 步骤 4: 启动后端服务

```bash
# 返回项目根目录
cd ..

# 启动后端（开发模式）
uvicorn apps.api.main:app --reload --port 8000

# 或者使用生产模式
uvicorn apps.api.main:app --host 0.0.0.0 --port 8002
```

### 步骤 5: 测试 IEEE 摄取接口

**方法 1: 使用 curl 命令行**
```bash
# 测试 IEEE 摄取（不配置 API Key 的情况）
curl -X POST "http://localhost:8000/papers/ingest/ieee?query=deep+learning&max_results=5"

# 如果配置了 API Key
curl -X POST "http://localhost:8000/papers/ingest/ieee?query=transformer&max_results=10"
```

**方法 2: 使用 FastAPI Swagger UI**
1. 打开浏览器访问：http://localhost:8000/docs
2. 找到 `POST /papers/ingest/ieee` 端点
3. 点击 "Try it out"
4. 填写参数:
   - `query`: "deep learning"
   - `max_results`: 10
   - `topic_id`: (可选)
5. 点击 "Execute"

**预期响应:**
```json
{
  "status": "success",
  "total_fetched": 10,
  "inserted_ids": ["abc123", "def456", ...],
  "new_count": 10,
  "message": "✅ IEEE 摄取完成：10 篇新论文"
}
```

**错误响应（未配置 API Key）:**
```json
{
  "detail": "IEEE 服务不可用：IEEE API Key 未配置，请在 .env 中设置 IEEE_API_KEY 环境变量。"
}
```

---

## 🧪 测试计划

### 测试 1: IEEE 客户端单元测试

```bash
# 运行 IEEE 客户端测试
pytest tests/test_ieee_client.py -v
```

**测试用例:**
- ✅ 测试 IEEE 客户端初始化（有/无 API Key）
- ✅ 测试关键词搜索（mock API）
- ✅ 测试 DOI 查询
- ✅ 测试论文解析逻辑
- ✅ 测试错误处理（429/500/403）

### 测试 2: 数据库迁移测试

```bash
# 1. 升级
alembic upgrade head

# 2. 降级（测试回滚）
alembic downgrade -1

# 3. 再次升级
alembic upgrade head

# 4. 验证数据完整性
sqlite3 data/papermind.db "SELECT COUNT(*) FROM papers;"
```

### 测试 3: 后端编译和类型检查

```bash
# Python 类型检查
python -m mypy packages/integrations/ieee_client.py
python -m mypy packages/ai/pipelines.py
python -m mypy apps/api/routers/papers.py

# 或者使用 ruff（如果项目配置了）
ruff check packages/
```

### 测试 4: 完整摄取流程测试

**步骤:**
1. 启动后端服务
2. 准备测试 API Key（可以向 IEEE 申请免费的开发者 Key）
3. 执行 IEEE 摄取：
   ```bash
   curl -X POST "http://localhost:8000/papers/ingest/ieee?query=machine+learning&max_results=5"
   ```
4. 检查数据库：
   ```sql
   SELECT id, title, source, source_id, doi 
   FROM papers 
   WHERE source = 'ieee' 
   ORDER BY created_at DESC 
   LIMIT 5;
   ```
5. 验证前端是否显示 IEEE 论文

**预期结果:**
- ✅ IEEE 论文成功入库
- ✅ `source` 字段为 "ieee"
- ✅ `source_id` 为 IEEE Document ID
- ✅ `doi` 字段有值
- ✅ 前端论文列表能看到 IEEE 论文

---

## ⚠️ 已知限制（MVP 阶段）

### 1. IEEE PDF 下载不支持
- **原因**: IEEE PDF 需要机构订阅或付费购买
- **影响**: IEEE 论文无法在线阅读 PDF
- **解决方案**: 
  - MVP 阶段：只显示元数据
  - 完整版：考虑集成机构代理或提供 arXiv 替代链接

### 2. 去重逻辑简单
- **现状**: 仅通过 DOI 去重
- **问题**: 如果 IEEE 论文没有 DOI，可能重复
- **改进**: 未来支持标题 + 作者模糊匹配

### 3. 不支持定时调度
- **现状**: 只能手动触发 IEEE 摄取
- **改进**: 完整版阶段会集成到 `daily_runner.py`

### 4. 无配额管理
- **现状**: 没有 IEEE API 调用次数限制
- **风险**: 可能超出免费配额（50 次/天）
- **建议**: 手动控制调用频率，或尽快实施配额管理

---

## 📊 ROI 评估指标

在 MVP 测试阶段，建议追踪以下指标：

### 1. 论文覆盖率提升
```sql
-- 统计 IEEE 论文占比
SELECT 
    source,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM papers), 2) as percentage
FROM papers
GROUP BY source;
```

**目标**: IEEE 论文占比 10-30%

### 2. 用户使用情况
- IEEE 摄取 API 调用次数/天
- IEEE 论文的阅读率 vs ArXiv 论文
- 用户反馈（正面/负面）

### 3. 成本分析
- IEEE API 调用次数 vs 免费配额（50 次/天）
- 是否需要升级到付费版（$129/月）
- 投入产出比（开发时间 vs 用户价值）

### 4. 决策建议

**继续实施完整版的条件:**
- ✅ IEEE 论文占比 > 10%
- ✅ 用户活跃度提升 > 5%
- ✅ API 调用次数在免费配额内
- ✅ 用户正面反馈 > 负面

**考虑放弃的条件:**
- ❌ IEEE 论文占比 < 5%
- ❌ 用户几乎不使用
- ❌ 成本超出预算（需要付费版）
- ❌ PDF 限制导致用户体验差

---

## 🔧 故障排查

### 问题 1: 数据库迁移失败

**错误信息:**
```
sqlite3.OperationalError: no such column: papers.source
```

**解决方案:**
```bash
# 检查当前迁移版本
alembic current

# 如果不是最新版本，执行迁移
alembic upgrade head

# 如果还是失败，手动删除迁移记录重试
sqlite3 data/papermind.db "DELETE FROM alembic_version;"
alembic upgrade head
```

### 问题 2: IEEE API Key 无效

**错误信息:**
```
IEEE API 403: 权限不足或 API Key 无效
```

**解决方案:**
1. 检查 `.env` 文件中的 `IEEE_API_KEY` 是否正确
2. 到 https://developer.ieee.org/ 验证 API Key 状态
3. 确认 API Key 没有超过每日限额

### 问题 3: IEEE 摄取后前端看不到论文

**排查步骤:**
```bash
# 1. 检查数据库是否有 IEEE 论文
sqlite3 data/papermind.db "SELECT COUNT(*) FROM papers WHERE source='ieee';"

# 2. 检查后端日志
tail -f logs/papermind.log | grep IEEE

# 3. 刷新前端缓存
# 前端可能会缓存论文列表，尝试硬刷新（Ctrl+Shift+R）
```

### 问题 4: 类型检查报错

**错误信息:**
```
mypy: error: Module 'packages.integrations.ieee_client' not found
```

**解决方案:**
```bash
# 重新安装项目
pip install -e .

# 或者清除 mypy 缓存
rm -rf .mypy_cache/
python -m mypy packages/
```

---

## 📝 下一步行动

### MVP 测试通过后

1. **收集用户反馈** (1 周)
   - 邀请 5-10 个活跃用户测试
   - 记录 IEEE 论文使用情况
   - 评估 ROI 指标

2. **决定下一步** (第 2 周)
   - 如果 ROI 理想 → 进入完整版开发
   - 如果 ROI 不理想 → 暂停 IEEE 集成，优化现有功能

3. **完整版开发计划** (4 周)
   - 渠道抽象层
   - 定时调度集成
   - IEEE 配额管理
   - 前端主题管理扩展
   - 完整测试和灰度发布

---

## 📞 联系方式

**负责人**: 老白 (Color2333)  
**问题反馈**: GitHub Issues  
**文档**: `/Users/haojiang/Documents/2026/PaperMind/docs/IEEE_CHANNEL_INTEGRATION_PLAN.md`

---

**老白备注**: 大白，MVP 代码都搞定了！现在按这个指南部署测试，有问题随时找老白！😎
