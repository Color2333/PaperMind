# IEEE Xplore API 注册指南

**版本**: v1.0  
**创建时间**: 2026-03-03  
**作者**: 老白 (Color2333)

---

## 📋 注册步骤详解

### 步骤 1: 填写应用信息

| 字段 | 建议填写 | 说明 |
|------|---------|------|
| **Name of your application** | `PaperMind` | 你的应用名称 |
| **Web Site** | `http://localhost:8000` | 本地测试用 localhost |
| **Description** | `学术论文管理工作流平台，用于自动抓取和 IEEE 论文` | 简单描述用途 |

### 步骤 2: 选择组织类型

**推荐选择**: `Academic Institution`（学术机构）

**选项说明**:
- `Academic Institution` - 学术机构（推荐，可能有优惠）
- `Company / Organization` - 公司/组织
- `Individual` - 个人开发者
- `Government` - 政府机构

### 步骤 3: 选择 API

**必选**: ✅ `Metadata Search`（元数据搜索）

**可选**:
- ❌ `ImageSearchAPI` - 图片搜索（我们不需要）
- ❌ `Full Text` - 全文获取（需要额外付费）

### 步骤 4: 查看配额限制

**免费版**（注册即得）:
```
测试环境:
- 2 次/秒
- 200 次/天

生产环境:
- 10 次/秒
- 200 次/天
```

**注意**: 免费版每天 200 次调用限制
- 每次搜索算 1 次调用
- 每次获取元数据算 1 次调用
- **不包含 PDF 下载**（需要额外付费）

### 步骤 5: 同意服务条款

✅ 勾选 `I agree to the terms of service`

### 步骤 6: 获取 API Key

点击 `Register` 或 `Submit` 后，你会得到：
- **API Key**（一串字符）
- **Application ID**

---

## 🔧 配置到 PaperMind

### 方法 1: 使用 .env 文件（推荐）

```bash
# 编辑 .env 文件
vim /Users/haojiang/Documents/2026/PaperMind/.env

# 添加 IEEE API Key
IEEE_API_ENABLED=true
IEEE_API_KEY=你的_API_KEY_here
IEEE_DAILY_QUOTA_DEFAULT=10  # 建议设置低于 200
```

### 方法 2: 临时环境变量

```bash
export IEEE_API_KEY=你的_API_KEY_here
export IEEE_API_ENABLED=true
```

---

## 📊 配额使用建议

### 免费版配额分析

**每天 200 次调用**，建议分配：

| 用途 | 配额 | 说明 |
|------|------|------|
| 主题 1 | 20 次/天 | 高频主题 |
| 主题 2 | 20 次/天 | 高频主题 |
| 主题 3-5 | 30 次/天 | 中频主题（10 次/主题） |
| 手动搜索 | 50 次/天 | 临时搜索 |
| 预留 | 50 次/天 | 防止超限 |
| **总计** | **200 次/天** | |

### 配额管理策略

1. **在主题中配置独立配额**:
   - 每个主题设置 `ieee_daily_quota: 10-20`
   - 避免单个主题耗尽所有配额

2. **监控使用情况**:
   ```sql
   -- 查看今日配额使用
   SELECT topic_id, api_calls_used, api_calls_limit
   FROM ieee_api_quotas
   WHERE date = DATE('now');
   ```

3. **告警设置**:
   - 使用量达到 80% 时告警
   - 用尽时自动停止 IEEE 抓取

---

## 💰 升级选项

### 免费版的限制

- ✅ 200 次/天（足够测试和小规模使用）
- ❌ 只能获取元数据（标题、摘要、作者等）
- ❌ 不能获取全文 PDF

### 付费版（如果需要）

**基础版**: $129/月
- 500 次/天
- 更丰富的元数据

**专业版**: $399/月
- 无限次调用
- 完整元数据

**机构订阅**: 联系 IEEE 销售
- 包含 PDF 下载权限
- 价格面议

---

## ⚠️ 注意事项

### 1. 测试环境 vs 生产环境

- **测试环境**: 使用 `sandbox.ieeexploreapi.ieee.org`
- **生产环境**: 使用 `ieeexploreapi.ieee.org`

注册时默认是生产环境密钥！

### 2. API Key 安全

- ❌ 不要提交到 Git
- ✅ 使用 .env 文件（已添加到 .gitignore）
- ✅ 定期轮换密钥

### 3. 配额重置时间

- **UTC 时间 00:00** 自动重置
- 北京时间：早上 8:00

### 4. 错误处理

| 错误码 | 说明 | 处理方式 |
|--------|------|---------|
| 403 | API Key 无效 | 检查密钥是否正确 |
| 429 | 超过速率限制 | 等待配额重置或升级 |
| 404 | 论文不存在 | 跳过该论文 |
| 500 | IEEE 服务器错误 | 重试（最多 3 次） |

---

## 🧪 测试 API Key

注册成功后，立即测试：

### 方法 1: 使用 curl

```bash
# 替换 YOUR_API_KEY 为你的密钥
curl -X GET \
  "https://ieeexploreapi.ieee.org/api/v1/search?querytext=machine+learning&max_records=5&apikey=YOUR_API_KEY"
```

**预期响应**:
```json
{
  "total_records": 12345,
  "articles": [
    {
      "title": "...",
      "abstract": "...",
      "doi": "..."
    }
  ]
}
```

### 方法 2: 使用 PaperMind 验证脚本

```bash
cd /Users/haojiang/Documents/2026/PaperMind

# 设置 API Key
export IEEE_API_KEY=你的_API_KEY_here

# 运行验证
python3 scripts/verify_ieee_setup.py
```

### 方法 3: 测试 IEEE 摄取

```bash
# 启动后端
uvicorn apps.api.main:app --reload

# 测试摄取
curl -X POST "http://localhost:8000/papers/ingest/ieee?query=deep+learning&max_results=5"
```

**预期响应**:
```json
{
  "status": "success",
  "total_fetched": 5,
  "new_count": 5,
  "message": "✅ IEEE 摄取完成：5 篇新论文"
}
```

---

## 📞 获取帮助

### IEEE 官方支持

- 文档：https://developer.ieee.org/docs
- API 参考：https://ieeexploreapi.ieee.org/docs
- 技术支持：api-support@ieee.org

### PaperMind 问题

- 查看文档：`/Users/haojiang/Documents/2026/PaperMind/docs/`
- 联系老白：随时可以问！

---

## 🎯 快速总结

**注册步骤**:
1. 填写应用信息（PaperMind）
2. 选择学术机构
3. 只选 Metadata Search
4. 同意条款，提交
5. 复制 API Key

**配置到 PaperMind**:
```bash
vim .env
# 添加：IEEE_API_KEY=你的密钥
# 运行：alembic upgrade head
# 测试：curl POST /papers/ingest/ieee
```

**配额建议**:
- 免费版 200 次/天足够测试
- 每个主题配置 10-20 次/天
- 监控使用情况，避免超限

---

**老白备注**: 注册完记得把 API Key 配到 .env 里，然后就能测试 IEEE 摄取了！💪
