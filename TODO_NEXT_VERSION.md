# PaperMind 版本规划 TODO

## 下一个版本 (v1.1.0) - 重点功能

### 🎯 核心功能：IEEE 文章抓取能力

**背景**：当前 PaperMind 仅支持 arXiv 文章抓取，需要扩展支持 IEEE Xplore 平台的文章获取能力。

---

### 📋 任务清单

#### 1. IEEE API 接入准备
- [ ] 申请 IEEE Xplore API Key（联系 `onlinesupport@ieee.org`）
- [ ] 确认机构订阅状态（如有）
- [ ] 阅读并理解 [IEEE API 服务条款](https://developer.ieee.org/API_Terms_of_Use2)
- [ ] 测试 API 连通性和基础查询功能

#### 2. 技术实现
- [ ] 设计多源架构（统一接口支持 arXiv、IEEE 等）
- [ ] 实现 IEEE API 客户端模块
  - [ ] 元数据搜索功能
  - [ ] Open Access 全文下载
  - [ ] DOI 解析功能
- [ ] 集成第三方开放资源
  - [ ] Unpaywall API（开放全文获取）
  - [ ] Semantic Scholar API（补充元数据）
  - [ ] TechRxiv 预印本检索
- [ ] 统一数据模型（兼容不同来源的论文格式）

#### 3. 合规与风险控制
- [ ] 实现请求频率限制（避免 IP 被封）
- [ ] 添加用户订阅状态检测
- [ ] 区分 Open Access 与付费文章的处理逻辑
- [ ] 编写合规使用文档

#### 4. 测试与验证
- [ ] 单元测试（API 客户端）
- [ ] 集成测试（端到端流程）
- [ ] 手动测试（真实 IEEE 文章下载）
- [ ] 性能测试（批量查询场景）

#### 5. 文档更新
- [ ] 用户文档：如何配置 IEEE API Key
- [ ] 开发文档：多源架构设计说明
- [ ] 更新 README.md 功能列表
- [ ] 编写常见问题 FAQ

---

### 📊 技术方案对比

| 方案 | 描述 | 可行性 | 优先级 |
|------|------|--------|--------|
| IEEE 官方 API (元数据) | 使用官方 API 获取文章信息 | ⭐⭐⭐⭐⭐ | P0 |
| IEEE API + Open Access | 下载 Open Access 全文 | ⭐⭐⭐⭐ | P0 |
| Unpaywall 整合 | 通过 DOI 查询开放版本 | ⭐⭐⭐⭐ | P1 |
| 机构订阅访问 | 用户自有订阅的论文下载 | ⭐⭐⭐ | P1 |
| 预印本检索 | TechRxiv/arXiv 预印本 | ⭐⭐⭐ | P2 |

---

### ⚠️ 风险与注意事项

1. **法律合规**：
   - 禁止大规模下载付费文章
   - 禁止重新分发 IEEE 内容
   - 仅限非商业用途

2. **技术风险**：
   - API Key 申请可能需要时间审批
   - 无机构订阅时全文获取能力受限
   - 需要处理反爬机制（如使用非官方途径）

3. **用户预期管理**：
   - 明确告知用户需要自己的机构订阅
   - Open Access 文章比例有限（约 10-20%）
   - 提供替代方案建议（预印本、开放资源）

---

### 🔗 参考资料

- [IEEE Xplore API 文档](https://developer.ieee.org/docs/read/IEEE_Xplore_Metadata_API_Overview)
- [IEEE API 使用案例](https://developer.ieee.org/Allowed_API_Uses)
- [Unpaywall API](https://unpaywall.org/products/api)
- [Semantic Scholar API](https://www.semanticscholar.org/product/api)
- [TechRxiv 预印本平台](https://www.techrxiv.org/)

---

### 📅 预计时间线

| 阶段 | 时间 | 里程碑 |
|------|------|--------|
| API 申请与调研 | Week 1 | 获得 API Key，完成技术验证 |
| 核心开发 | Week 2-3 | IEEE 客户端完成，基础功能可用 |
| 整合测试 | Week 4 | 多源整合完成，测试通过 |
| 文档与发布 | Week 5 | 文档完善，版本发布 |

---

### 📝 调研摘要

详见调研记录（2026-03-03）：
- arXiv vs IEEE 访问模式对比
- IEEE API 技术细节与限制
- 法律合规性分析
- 推荐实施方案

**核心结论**：技术上完全可行，优先采用官方 API + 多源开放资源的合规方案，避免暴力爬虫。

---

*最后更新：2026-03-03*
*创建人：老白*
