# 每日自动精读与邮件报告功能

> 完成时间：2026-02-26
> 作者：Color2333

## 🎯 功能概述

实现了完整的每日自动化工作流：
1. **每日搜集论文** → 自动精读 → 生成汇总报告 → 邮箱发送

---

## ✨ 核心功能

### 1. 邮箱配置管理

#### 功能特性
- ✅ 支持多个邮箱配置
- ✅ 常见邮箱服务商预设（Gmail、QQ、163、Outlook）
- ✅ 一键激活/切换邮箱
- ✅ 发送测试邮件验证配置
- ✅ TLS 加密支持
- ✅ 应用专用密码支持

#### 数据模型
```python
class EmailConfig(Base):
    id: str                     # 唯一标识
    name: str                   # 配置名称（如"工作邮箱"）
    smtp_server: str            # SMTP 服务器地址
    smtp_port: int              # SMTP 端口（默认 587）
    smtp_use_tls: bool          # 是否使用 TLS
    sender_email: str           # 发件人邮箱
    sender_name: str            # 发件人名称（默认 "PaperMind"）
    username: str               # SMTP 用户名
    password: str               # SMTP 密码（应用专用密码）
    is_active: bool             # 是否激活
```

#### API 端点
| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/settings/email-configs` | 获取所有邮箱配置 |
| POST | `/settings/email-configs` | 创建邮箱配置 |
| PATCH | `/settings/email-configs/{id}` | 更新邮箱配置 |
| DELETE | `/settings/email-configs/{id}` | 删除邮箱配置 |
| POST | `/settings/email-configs/{id}/activate` | 激活邮箱配置 |
| POST | `/settings/email-configs/{id}/test` | 发送测试邮件 |
| GET | `/settings/smtp-presets` | 获取 SMTP 预设 |

---

### 2. 每日报告配置

#### 功能特性
- ✅ 总开关控制（启用/禁用）
- ✅ 自动精读设置（开关 + 数量限制）
- ✅ 邮件发送设置（开关 + 收件人 + 发送时间）
- ✅ 报告内容设置（论文详情 + 图谱洞察）
- ✅ 手动触发工作流

#### 数据模型
```python
class DailyReportConfig(Base):
    enabled: bool                      # 总开关
    auto_deep_read: bool               # 自动精读开关
    deep_read_limit: int               # 每日精读数量限制（默认 10）
    send_email_report: bool            # 发送邮件报告开关
    recipient_emails: str              # 收件人邮箱列表（逗号分隔）
    report_time_utc: int               # 发送时间（UTC 0-23）
    include_paper_details: bool        # 是否包含论文详情
    include_graph_insights: bool       # 是否包含图谱洞察
```

#### API 端点
| 方法 | 路径 | 说明 |
|:----:|:-----|:-----|
| GET | `/settings/daily-report-config` | 获取每日报告配置 |
| PUT | `/settings/daily-report-config` | 更新每日报告配置 |
| POST | `/jobs/daily-report/run-once` | 手动触发工作流 |

---

### 3. 自动精读服务

#### 工作流程
```
每日搜集论文 → 筛选未精读论文 → 限制数量 → 并行精读 → 生成简报 → 发送邮件
```

#### 核心逻辑
```python
class AutoReadService:
    async def run_daily_workflow(progress_callback):
        # 1. 自动精读新论文
        if config.auto_deep_read:
            papers = get_recent_papers(limit=config.deep_read_limit)
            for paper in papers:
                await pipelines.run_deep_read(paper.id)

        # 2. 生成每日简报
        brief = await DailyBriefService().generate_daily_brief()

        # 3. 发送邮件报告
        if config.send_email_report:
            email_service = EmailService(email_config)
            email_service.send_daily_report(
                to_emails=recipient_emails,
                report_html=brief.html,
                report_date=today
            )
```

#### 邮件模板
```html
<!DOCTYPE html>
<html>
<head>
    <style>
        /* 响应式邮件样式 */
    </style>
</head>
<body>
    <div class="header">
        <h1>📚 PaperMind 每日简报</h1>
        <p>{日期}</p>
    </div>
    <div class="content">
        <!-- 新搜集的论文 -->
        <!-- 自动精读的论文 -->
        <!-- 研究趋势分析 -->
        <!-- 个性化推荐 -->
    </div>
</body>
</html>
```

---

## 📁 新增文件

### 后端
- `packages/storage/models.py` - 添加 `EmailConfig` 和 `DailyReportConfig` 模型
- `packages/storage/repositories.py` - 添加 `EmailConfigRepository` 和 `DailyReportConfigRepository`
- `packages/integrations/email_service.py` - 邮箱发送服务
- `packages/ai/auto_read_service.py` - 自动精读调度服务
- `apps/api/main.py` - 添加邮箱和每日报告 API 路由
- `infra/migrations/versions/20260226_0007_email_and_auto_read.py` - 数据库迁移脚本

### 前端
- `frontend/src/pages/EmailSettings.tsx` - 邮箱和每日报告设置页面
- `frontend/src/App.tsx` - 添加 `/email-settings` 路由

---

## 🗄️ 数据库迁移

### 迁移版本
`20260226_0007_email_and_auto_read`

### 新增表
#### `email_configs`
```sql
CREATE TABLE email_configs (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(128) UNIQUE NOT NULL,
    smtp_server VARCHAR(256) NOT NULL,
    smtp_port INTEGER DEFAULT 587,
    smtp_use_tls BOOLEAN DEFAULT TRUE,
    sender_email VARCHAR(256) NOT NULL,
    sender_name VARCHAR(128) DEFAULT 'PaperMind',
    username VARCHAR(256) NOT NULL,
    password VARCHAR(512) NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
```

#### `daily_report_configs`
```sql
CREATE TABLE daily_report_configs (
    id VARCHAR(36) PRIMARY KEY,
    enabled BOOLEAN DEFAULT FALSE,
    auto_deep_read BOOLEAN DEFAULT TRUE,
    deep_read_limit INTEGER DEFAULT 10,
    send_email_report BOOLEAN DEFAULT TRUE,
    recipient_emails VARCHAR(2048) DEFAULT '',
    report_time_utc INTEGER DEFAULT 21,
    include_paper_details BOOLEAN DEFAULT TRUE,
    include_graph_insights BOOLEAN DEFAULT FALSE,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);
```

---

## 🚀 使用指南

### 1. 配置邮箱

#### 步骤
1. 访问 **http://localhost:5173/email-settings**
2. 点击 **"添加邮箱"**
3. 选择快速配置（Gmail/QQ/163/Outlook）或手动配置
4. 填写邮箱信息和应用专用密码
5. 点击 **"发送测试"** 验证配置
6. 测试成功后，点击 **"激活"** 设为默认邮箱

#### 应用专用密码获取
- **Gmail**: Google Account → Security → 2-Step Verification → App passwords
- **QQ邮箱**: 设置 → 账户 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务 → 生成授权码
- **163邮箱**: 设置 → POP3/SMTP/IMAP → 开启服务 → 获取授权码

### 2. 配置每日报告

#### 步骤
1. 在邮箱设置页面，找到 **"每日报告配置"** 卡片
2. 点击 **"启用"** 开启总开关
3. 配置自动精读：
   - 勾选 **"自动精读新论文"**
   - 设置 **"每日精读数量限制"**（建议 5-20 篇）
4. 配置邮件发送：
   - 勾选 **"发送邮件报告"**
   - 填写 **"收件人邮箱"**（多个邮箱用逗号分隔）
   - 设置 **"发送时间（UTC）"**（北京时间 = UTC + 8）
   - 例如：北京时间早上 8 点 = UTC 0 点
5. 配置报告内容：
   - 勾选 **"包含论文详情"**
   - 勾选 **"包含图谱洞察"**（可选）

### 3. 手动触发工作流

#### 步骤
1. 在邮箱设置页面，点击 **"立即执行"** 按钮
2. 确认执行
3. 等待自动精读、生成简报、发送邮件完成
4. 查看成功提示（精读了 X 篇论文）

---

## 📊 工作流时序图

```
时间轴（每日）
  ↓
[定时任务触发]
  ↓
[搜集新论文] ← 已有功能（TopicSubscription）
  ↓
[自动精读] ← 新功能（AutoReadService）
  ├─ 筛选未精读论文
  ├─ 限制数量（deep_read_limit）
  └─ 并行执行精读（Pipeline）
  ↓
[生成每日简报] ← 已有功能（DailyBriefService）
  ├─ 新搜集的论文列表
  ├─ 自动精读的关键论文
  ├─ 研究趋势分析
  └─ 个性化推荐
  ↓
[发送邮件报告] ← 新功能（EmailService）
  ├─ HTML 格式邮件
  ├─ 响应式设计
  └─ 多收件人支持
  ↓
[完成]
```

---

## ⚙️ 定时任务集成

### 现有定时任务（每日）
```python
# packages/ai/daily_runner.py

async def run_daily_brief():
    """生成每日简报（已有）"""
    ...

# 新增：集成自动精读和邮件发送
async def run_daily_workflow():
    """完整的每日工作流"""
    # 1. 搜集新论文（已有）
    await run_daily_ingest()

    # 2. 自动精读（新增）
    await AutoReadService().run_daily_workflow()
```

### Cron 配置
```python
# packages/ai/daily_runner.py

# 每日简报生成（已有）
DAILY_CRON = "0 21 * * *"  # UTC 21:00（北京时间早上 5:00）

# 自动精读和邮件发送（新增）
# 在每日简报生成后立即执行
```

---

## 🎨 前端界面

### 邮箱设置页面
- **位置**: `/email-settings`
- **功能**:
  - 邮箱配置列表
  - 添加/编辑/删除邮箱
  - 激活邮箱
  - 发送测试邮件
  - 每日报告配置
  - 手动触发工作流

### UI 特性
- ✅ 响应式设计
- ✅ 暗色模式支持
- ✅ 实时状态反馈
- ✅ 错误提示和确认对话框
- ✅ 加载状态和进度显示

---

## 🔧 技术栈

### 后端
- **FastAPI** - API 框架
- **SQLAlchemy** - ORM
- **Alembic** - 数据库迁移
- **smtplib** - 邮件发送（Python 标准库）
- **APScheduler** - 定时任务调度（已有）

### 前端
- **React 18** - UI 框架
- **TypeScript** - 类型安全
- **Lucide Icons** - 图标库
- **Tailwind CSS** - 样式

---

## 🐛 常见问题

### Q1: 测试邮件发送失败？
**A**: 检查以下几点：
1. SMTP 服务器地址和端口是否正确
2. 是否使用了应用专用密码（而非账户密码）
3. 是否开启了 SMTP 服务（QQ/163 需要手动开启）
4. 防火墙是否阻止了 SMTP 端口

### Q2: 没有收到每日报告邮件？
**A**: 检查以下几点：
1. 每日报告总开关是否启用
2. 邮箱配置是否已激活
3. 收件人邮箱是否正确填写
4. 检查垃圾邮件文件夹

### Q3: 自动精读没有执行？
**A**: 检查以下几点：
1. 是否有新搜集的论文
2. 自动精读开关是否启用
3. 检查后端日志是否有错误

### Q4: 如何调整发送时间？
**A**:
1. 设置 **"报告时间（UTC）"**
2. 北京时间 = UTC + 8
3. 例如：
   - 北京时间早上 8 点 → UTC 0 点
   - 北京时间晚上 8 点 → UTC 12 点

---

## 📝 后续优化建议

1. **定时任务可视化**
   - 添加 Cron 表达式可视化编辑器
   - 显示下次执行时间

2. **邮件模板定制**
   - 支持自定义邮件模板
   - 支持多种报告格式（PDF、Markdown）

3. **报告历史**
   - 保存历史报告记录
   - 支持重新发送历史报告

4. **失败重试**
   - 添加邮件发送失败重试机制
   - 失败通知和日志记录

5. **收件人分组**
   - 支持创建收件人分组
   - 不同分组发送不同内容

---

## 📄 License

MIT

---

**Built with ❤️ by Color2333**
