# IEEE 配额管理系统 - 完整版实施指南

**版本**: v2.0-Alpha  
**创建时间**: 2026-03-03  
**作者**: 老白 (Color2333)

---

## 📦 配额管理系统架构

### 数据模型

```python
class IeeeApiQuota(Base):
    __tablename__ = "ieee_api_quotas"
    
    id: str  # 主键
    topic_id: str  # 主题 ID（外键）
    date: date  # 日期（按日期追踪）
    api_calls_used: int  # 已使用次数
    api_calls_limit: int  # 限额（默认 50 次/天）
    last_reset_at: datetime  # 最后重置时间
```

### Repository 接口

```python
class IeeeQuotaRepository:
    - get_or_create(topic_id, date, limit) -> IeeeApiQuota
    - check_quota(topic_id, date, limit) -> bool
    - consume_quota(topic_id, date, amount=1) -> bool
    - get_remaining(topic_id, date) -> int
    - reset_quota(topic_id, date, new_limit) -> None
```

---

## 🔧 使用方式

### 1. 在定时任务中使用

```python
from packages.storage.repositories import IeeeQuotaRepository
from datetime import date

def _ingest_from_ieee(pipelines, topic, session) -> dict:
    """IEEE 渠道抓取 - 带配额检查"""
    
    quota_repo = IeeeQuotaRepository(session)
    today = date.today()
    limit = getattr(topic, "ieee_daily_quota", 10)
    
    # 检查配额
    if not quota_repo.check_quota(topic.id, today, limit):
        logger.warning("IEEE 配额已用尽")
        return {"status": "quota_exhausted", "inserted": 0}
    
    # 执行抓取
    total, inserted_ids, new_count = pipelines.ingest_ieee(...)
    
    # 消耗配额
    quota_repo.consume_quota(topic.id, today, 1)
    
    return {"status": "ok", "inserted": len(inserted_ids)}
```

### 2. 配额查询

```python
# 查询剩余配额
remaining = quota_repo.get_remaining(topic_id, date.today())
logger.info("IEEE 剩余配额：%d", remaining)

# 手动重置配额
quota_repo.reset_quota(topic_id, date.today(), new_limit=100)
```

---

## 📊 配额策略

### 默认配额

| 用户类型 | 每日配额 | 说明 |
|---------|---------|------|
| 免费版 | 10 次/天 | 适合个人测试 |
| 付费版 | 50 次/天 | IEEE 免费 API 上限 |
| 机构版 | 500 次/天 | 需自费购买 IEEE API |

### 配额告警

**告警阈值:**
- 80% 使用量：发送提醒邮件
- 100% 使用量：停止 IEEE 抓取，发送告警邮件

**告警逻辑:**
```python
def check_quota_alert(topic_id: str, session):
    """检查配额告警"""
    quota_repo = IeeeQuotaRepository(session)
    today = date.today()
    
    quota = quota_repo.get_or_create(topic_id, today)
    usage_percent = quota.api_calls_used / quota.api_calls_limit
    
    if usage_percent >= 1.0:
        send_alert_email("IEEE 配额已用尽", topic_id)
    elif usage_percent >= 0.8:
        send_warning_email("IEEE 配额即将用尽", topic_id)
```

---

## 🗄️ 数据库迁移

### 执行迁移

```bash
cd infra
alembic upgrade head
```

### 验证迁移

```sql
-- 检查表是否创建成功
sqlite3 data/papermind.db

-- 查看表结构
.schema ieee_api_quotas

-- 应该看到：
-- CREATE TABLE ieee_api_quotas (
--   id VARCHAR(36) NOT NULL PRIMARY KEY,
--   topic_id VARCHAR(36),
--   date DATE NOT NULL,
--   api_calls_used INTEGER NOT NULL DEFAULT 0,
--   api_calls_limit INTEGER NOT NULL DEFAULT 50,
--   last_reset_at DATETIME,
--   created_at DATETIME NOT NULL,
--   FOREIGN KEY(topic_id) REFERENCES topic_subscriptions(id)
-- );
```

---

## ⚠️ 注意事项

### 1. 配额重置

- 配额按日期追踪，UTC 时间 00:00 自动重置
- 可以通过 `reset_quota()` 手动重置

### 2. 并发控制

- 同一主题的并发抓取需要加锁
- 使用数据库事务保证配额扣减原子性

### 3. 性能优化

- 配额查询使用索引（topic_id + date）
- 缓存配额状态（Redis/Memory）避免频繁查库

---

## 📈 监控指标

### 每日追踪

```sql
-- 查看今日各主题 IEEE 配额使用情况
SELECT 
    t.name as topic_name,
    q.api_calls_used,
    q.api_calls_limit,
    ROUND(q.api_calls_used * 100.0 / q.api_calls_limit, 2) as usage_percent
FROM ieee_api_quotas q
LEFT JOIN topic_subscriptions t ON q.topic_id = t.id
WHERE q.date = DATE('now')
ORDER BY usage_percent DESC;
```

### 历史趋势

```sql
-- 查看近 7 天 IEEE 配额使用趋势
SELECT 
    q.date,
    SUM(q.api_calls_used) as total_used,
    SUM(q.api_calls_limit) as total_limit,
    ROUND(SUM(q.api_calls_used) * 100.0 / SUM(q.api_calls_limit), 2) as usage_percent
FROM ieee_api_quotas q
WHERE q.date >= DATE('now', '-7 days')
GROUP BY q.date
ORDER BY q.date;
```

---

## 🔧 故障排查

### 问题 1: 配额查询失败

**错误信息:**
```
sqlite3.OperationalError: no such table: ieee_api_quotas
```

**解决方案:**
```bash
# 执行数据库迁移
cd infra && alembic upgrade head
```

### 问题 2: 配额未正确扣减

**排查步骤:**
```python
# 手动检查配额记录
from packages.storage.repositories import IeeeQuotaRepository
from packages.storage.db import session_scope
from datetime import date

with session_scope() as session:
    quota_repo = IeeeQuotaRepository(session)
    quota = quota_repo.get_or_create("topic_id_here", date.today())
    print(f"已使用：{quota.api_calls_used}, 限额：{quota.api_calls_limit}")
```

---

**老白备注**: 配额管理系统搞定！现在继续干前端 UI！💪
