# IEEE 渠道集成 - 灰度发布和监控指南

**版本**: v2.0-Beta  
**创建时间**: 2026-03-03  
**作者**: 老白 (Color2333)  
**状态**: 待执行

---

## 📋 灰度发布计划

### 阶段 1: 内部测试（Week 1）

**目标**: 验证基本功能正常

**范围**: 开发团队（5-10 人）

**行动项**:
- [ ] 部署到生产环境
- [ ] 开启 IEEE 摄取功能开关
- [ ] 配置开发团队主题使用 IEEE
- [ ] 每日监控 IEEE API 调用
- [ ] 收集开发团队反馈

**成功标准**:
- ✅ IEEE 摄取成功率 >95%
- ✅ 无严重 Bug
- ✅ 开发团队正面反馈

### 阶段 2: 小范围公测（Week 2）

**目标**: 验证用户体验和 ROI

**范围**: 10% 活跃用户（约 50-100 人）

**行动项**:
- [ ] 筛选 10% 活跃用户
- [ ] 发送邮件通知新功能
- [ ] 开启 IEEE 渠道配置
- [ ] 监控用户使用情况
- [ ] 收集用户反馈问卷

**成功标准**:
- ✅ IEEE 论文占比 >10%
- ✅ 用户活跃度提升 >5%
- ✅ 正面反馈 > 负面

### 阶段 3: 全量发布（Week 3）

**目标**: 全面推广

**范围**: 100% 用户

**行动项**:
- [ ] 更新用户文档
- [ ] 全站功能公告
- [ ] 监控服务器负载
- [ ] 评估 IEEE API 成本
- [ ] 决定是否续费

**成功标准**:
- ✅ 系统稳定运行
- ✅ ROI 符合预期
- ✅ 用户满意度高

---

## 📊 监控指标

### 1. 技术指标

| 指标 | 告警阈值 | 说明 |
|------|---------|------|
| IEEE API 成功率 | <95% | 5 分钟平均值 |
| IEEE 摄取耗时 | >10 秒/次 | P95 延迟 |
| 数据库查询耗时 | >200ms | P95 延迟 |
| 配额使用率 | >80% | 每日检查 |

### 2. 业务指标

| 指标 | 目标 | 说明 |
|------|------|------|
| IEEE 论文占比 | >10% | IEEE 论文/总论文 |
| 用户活跃度 | +5% | DAU/MAU 变化 |
| IEEE 功能使用率 | >30% | 配置 IEEE 的主题占比 |
| 付费转化率 | +2% | IEEE 功能带来的转化 |

### 3. 成本指标

| 指标 | 预算 | 说明 |
|------|------|------|
| IEEE API 调用/天 | <50 次 | 免费额度 |
| 月度成本 | $0-129 | 根据使用情况 |

---

## 🚨 告警配置

### Prometheus 规则

```yaml
# prometheus/alerts.yml
groups:
  - name: ieee_integration
    rules:
      # IEEE API 成功率告警
      - alert: IeeeApiLowSuccessRate
        expr: avg(ieee_api_success_rate) < 0.95
        for: 5m
        annotations:
          summary: "IEEE API 成功率低于 95%"
      
      # IEEE 摄取耗时告警
      - alert: IeeeIngestSlow
        expr: histogram_quantile(0.95, rate(ieee_ingest_duration_bucket[5m])) > 10
        for: 5m
        annotations:
          summary: "IEEE 摄取 P95 延迟超过 10 秒"
      
      # IEEE 配额告警
      - alert: IeeeQuotaExhausted
        expr: ieee_quota_remaining < 5
        for: 1h
        annotations:
          summary: "IEEE 配额即将用尽"
```

### Grafana 仪表盘

```json
{
  "dashboard": {
    "title": "IEEE 集成监控",
    "panels": [
      {
        "title": "IEEE API 调用次数",
        "targets": [{ "expr": "sum(ieee_api_calls_total)" }]
      },
      {
        "title": "IEEE 论文占比",
        "targets": [{ "expr": "ieee_papers / total_papers * 100" }]
      },
      {
        "title": "IEEE 摄取耗时",
        "targets": [{ "expr": "histogram_quantile(0.95, rate(ieee_ingest_duration_bucket[5m]))" }]
      }
    ]
  }
}
```

---

## 📧 用户沟通

### 邮件通知模板

**主题**: 🎉 PaperMind 新增 IEEE Xplore 集成！

**正文**:
```
亲爱的用户，

我们很高兴地宣布 PaperMind 现已支持 IEEE Xplore 集成！

新功能:
✅ 同时从 ArXiv 和 IEEE 抓取论文
✅ IEEE 论文覆盖率提升 30%
✅ 智能配额管理，避免超额使用

如何使用:
1. 进入主题管理页面
2. 编辑或创建主题
3. 在"论文渠道"中选择 IEEE Xplore
4. 配置每日配额（建议 10-20 次/天）

注意事项:
- IEEE 需要 API Key（免费版 50 次/天）
- IEEE PDF 暂不支持在线阅读
- 配额用尽后自动跳过 IEEE 渠道

如有问题，请随时联系我们！

祝好，
PaperMind 团队
```

---

## 📈 ROI 评估

### 评估指标

```sql
-- IEEE 论文占比
SELECT 
    source,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM papers), 2) as percentage
FROM papers
GROUP BY source;

-- IEEE 功能使用率
SELECT 
    COUNT(CASE WHEN sources LIKE '%ieee%' THEN 1 END) * 100.0 / COUNT(*) as ieee_usage_percent
FROM topic_subscriptions;

-- 用户活跃度变化
SELECT 
    DATE(created_at) as date,
    COUNT(DISTINCT user_id) as dau
FROM user_activities
WHERE created_at >= DATE('now', '-30 days')
GROUP BY DATE(created_at)
ORDER BY date;
```

### 决策矩阵

| 指标 | 优秀 | 良好 | 需改进 | 决策 |
|------|------|------|--------|------|
| IEEE 论文占比 | >30% | 10-30% | <10% | <10% 考虑放弃 |
| 用户活跃度 | +10% | +5-10% | <5% | <5% 优化功能 |
| IEEE 使用率 | >50% | 30-50% | <30% | <30% 加强推广 |
| 成本效益 | 高 | 中 | 低 | 低则降级 API |

---

## ✅ 发布检查清单

### 发布前
- [ ] 所有集成测试通过
- [ ] 性能测试达标
- [ ] 监控仪表盘配置
- [ ] 告警规则配置
- [ ] 用户文档更新
- [ ] 邮件通知准备
- [ ] 回滚方案测试

### 发布后
- [ ] 监控系统运行正常
- [ ] IEEE API 调用正常
- [ ] 用户反馈收集
- [ ] 每日数据报告
- [ ] 周度 ROI 评估

---

## 🔄 回滚方案

### 触发条件

- IEEE API 成功率 <80% 持续 1 小时
- 严重 Bug 影响核心功能
- 成本超出预算 50%

### 回滚步骤

```bash
# 1. 关闭 IEEE 功能开关
UPDATE topic_subscriptions SET sources = '["arxiv"]' WHERE sources LIKE '%ieee%';

# 2. 禁用 IEEE API
# .env 设置
IEEE_API_ENABLED=false

# 3. 重启后端服务
systemctl restart papermind-backend

# 4. 验证回滚
curl http://localhost:8000/papers/latest
# 确认只有 ArXiv 论文
```

---

**老白备注**: 灰度计划写好，按步骤执行！💪
