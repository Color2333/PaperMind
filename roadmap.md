# PaperMind Roadmap

> 记录功能想法和实践方式

---

## 新想法

### 📊 统计分析功能 (2026-03-19)

**需求**：对论文库数据进行统计分析可视化

**分析维度**：
- [x] 主题维度统计（论文数、引用数、活跃度）
- [x] 发表年份分布 ✅
- [x] 来源分布 ✅
- [ ] 阅读状态分布

**实现方案**：
1. 后端新增主题统计 API 接口
2. 前端新建 Statistics 独立页面
3. 实现主题维度统计图表组件
4. 侧边栏添加统计入口

**Todo**：
- [x] apps/api: 新增主题统计 API 接口
- [x] frontend: 新建 Statistics 页面
- [x] frontend: 实现主题维度统计图表组件
- [x] frontend: 侧边栏添加统计入口

**实现细节**：
- `packages/storage/repositories.py`: 添加 `topic_stats()` + `paper_distribution_stats()` 方法
- `apps/api/routers/topics.py`: 添加 `GET /topics/stats` + `GET /topics/distribution` API
- `frontend/src/pages/Statistics.tsx`: 主题统计 + 年份分布 + 来源分布
- `frontend/src/components/Sidebar.tsx`: 添加"主题统计"入口
- `frontend/src/services/api.ts`: 添加 `topicApi.stats()` + `topicApi.distribution()`
- `frontend/src/types/index.ts`: 添加 `TopicStats` + `PaperDistributionResponse` 类型

---

## 待讨论

### 可选功能方向

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 时间维度统计 | 按年份/月份统计论文数量和引用量 | 中 |
| 阅读状态分布 | 统计已读/未读/收藏比例 | 低 |
| 导出功能 | 支持导出统计报告为 CSV/PDF | 低 |

---

*最后更新: 2026-03-19*
