# IEEE 渠道集成 - 完整测试计划

**版本**: v2.0-Beta  
**创建时间**: 2026-03-03  
**作者**: 老白 (Color2333)  
**状态**: 待执行

---

## 📋 测试清单

### 1. 单元测试（已完成 ✅）

| 测试文件 | 覆盖率 | 状态 |
|---------|--------|------|
| `tests/test_ieee_client.py` | 85% | ✅ 完成 |

### 2. 集成测试（待执行）

#### 2.1 数据库迁移测试

```bash
# 测试步骤
cd infra

# 1. 执行迁移
alembic upgrade head

# 2. 验证表结构
sqlite3 data/papermind.db ".schema papers"
sqlite3 data/papermind.db ".schema topic_subscriptions"
sqlite3 data/papermind.db ".schema ieee_api_quotas"

# 3. 验证回滚
alembic downgrade -1
alembic upgrade head

# 预期结果：
# - papers 表有 source/source_id/doi 字段
# - topic_subscriptions 表有 sources/ieee_daily_quota 字段
# - ieee_api_quotas 表创建成功
```

**状态**: ⏳ 待执行

#### 2.2 IEEE 摄取测试

```bash
# 1. 配置 IEEE API Key
export IEEE_API_KEY=your_key

# 2. 测试 MVP API
curl -X POST "http://localhost:8000/papers/ingest/ieee?query=deep+learning&max_results=5" \
  -H "Content-Type: application/json"

# 3. 验证数据库
sqlite3 data/papermind.db "SELECT COUNT(*) FROM papers WHERE source='ieee';"

# 预期结果：
# - API 返回 200 OK
# - 数据库有 IEEE 论文记录
# - source 字段为 "ieee"
```

**状态**: ⏳ 待执行

#### 2.3 多渠道调度测试

```python
# 测试脚本
from packages.ai.daily_runner import run_topic_ingest_v2
from packages.storage.db import session_scope
from packages.storage.models import TopicSubscription

with session_scope() as session:
    # 创建测试主题
    topic = TopicSubscription(
        name="test-multi-channel",
        query="machine learning",
        sources=["arxiv", "ieee"],
        ieee_daily_quota=5,
    )
    session.add(topic)
    session.commit()
    
    # 执行调度
    result = run_topic_ingest_v2(topic.id)
    
    # 验证结果
    assert "by_source" in result
    assert "arxiv" in result["by_source"]
    assert "ieee" in result["by_source"]
    print("✅ 多渠道调度测试通过")
```

**状态**: ⏳ 待执行

#### 2.4 配额管理测试

```python
# 测试脚本
from packages.storage.repositories import IeeeQuotaRepository
from packages.storage.db import session_scope
from datetime import date

with session_scope() as session:
    quota_repo = IeeeQuotaRepository(session)
    today = date.today()
    
    # 测试配额检查
    assert quota_repo.check_quota("topic_123", today, limit=10) == True
    
    # 测试配额消耗
    assert quota_repo.consume_quota("topic_123", today, 1) == True
    
    # 测试配额查询
    remaining = quota_repo.get_remaining("topic_123", today)
    assert remaining == 9
    
    # 测试配额用尽
    for i in range(9):
        quota_repo.consume_quota("topic_123", today, 1)
    
    assert quota_repo.check_quota("topic_123", today, limit=10) == False
    
    print("✅ 配额管理测试通过")
```

**状态**: ⏳ 待执行

### 3. 性能测试（待执行）

#### 3.1 IEEE API 并发测试

```python
# 测试脚本
import time
from concurrent.futures import ThreadPoolExecutor

def test_concurrent_ingest():
    """测试 IEEE 并发摄取性能"""
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(pipelines.ingest_ieee, f"query_{i}", 10)
            for i in range(10)
        ]
        results = [f.result() for f in futures]
    
    elapsed = time.time() - start
    print(f"并发摄取 10 次，耗时：{elapsed:.2f}秒")
    print(f"平均每次：{elapsed/10:.2f}秒")
    
    # 性能指标：<5 秒/次
    assert elapsed/10 < 5.0, "性能不达标"
```

**目标**: <5 秒/次 IEEE 摄取

#### 3.2 数据库查询性能

```sql
-- 测试索引效果
EXPLAIN QUERY PLAN
SELECT * FROM papers WHERE source='ieee' AND doi='10.1109/xxx';

-- 预期：使用索引 ix_papers_source 或 ix_papers_doi
```

**目标**: <100ms 查询

### 4. 端到端测试（待执行）

#### 4.1 完整流程测试

```
1. 创建主题（选择 ArXiv + IEEE）
   ↓
2. 配置 IEEE 配额（10 次/天）
   ↓
3. 触发定时调度
   ↓
4. 验证多渠道抓取
   ↓
5. 验证配额扣减
   ↓
6. 验证论文入库
   ↓
7. 前端显示 IEEE 论文
```

**状态**: ⏳ 待执行

---

## 🐛 已知 Bug 清单

| Bug ID | 描述 | 严重程度 | 状态 |
|--------|------|---------|------|
| - | 暂无 | - | - |

---

## 📊 测试指标

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
| 单元测试覆盖率 | >80% | 85% | ✅ |
| IEEE 摄取性能 | <5 秒/次 | 待测 | ⏳ |
| 数据库查询 | <100ms | 待测 | ⏳ |
| 端到端成功率 | 100% | 待测 | ⏳ |

---

## ✅ 测试完成标准

- [ ] 所有集成测试通过
- [ ] 性能测试达标
- [ ] 端到端流程验证
- [ ] 无严重 Bug
- [ ] 测试报告完成

---

**老白备注**: 测试计划写好，赶紧执行验证！💪
