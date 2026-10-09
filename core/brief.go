// 每日简报：选文（高分优先+回溯补齐）→ AI 洞察（LLM）→ HTML 渲染 →
// 邮件（effect ledger 防重）→ generated_contents proposal。
package core

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"html"
	"log"
	"os"
	"regexp"
	"strings"
	"time"
)

// userTodayStartUTC 用户时区当日 0 点（USER_TIMEZONE，默认 Asia/Shanghai）。
func userTodayStartUTC() time.Time {
	tz := envOr("USER_TIMEZONE", "Asia/Shanghai")
	loc, err := time.LoadLocation(tz)
	if err != nil {
		loc = time.UTC
	}
	now := time.Now().In(loc)
	y, m, d := now.Date()
	return time.Date(y, m, d, 0, 0, 0, 0, loc).UTC()
}

func userDateStr() string {
	tz := envOr("USER_TIMEZONE", "Asia/Shanghai")
	loc, err := time.LoadLocation(tz)
	if err != nil {
		loc = time.UTC
	}
	return time.Now().In(loc).Format("2006-01-02")
}

// briefPaper 简报条目。
type briefPaper struct {
	ID, Title, ArxivID, ReadStatus, Summary string
	SkimScore                               *float64
	Innovations                             []string
	HasDeepRead                             bool
	Topics                                  []string
}

// selectPapersForBrief 高分优先 + 回溯补齐（Python _select_papers_for_brief 三级策略）。
func (e *HandlerEnv) selectPapersForBrief(limit int) []briefPaper {
	todayStart := userTodayStartUTC()
	weekStart := todayStart.AddDate(0, 0, -6)
	threshold := 0.65
	if v := envOr("SKIM_SCORE_THRESHOLD", ""); v != "" {
		fmt.Sscanf(v, "%f", &threshold)
	}
	pick := func(since time.Time, minScore bool, lim int) []briefPaper {
		scoreFilter := ""
		args := []any{since.Format("2006-01-02 15:04:05.000000"), lim}
		if minScore {
			scoreFilter = ` AND COALESCE(ar.skim_score,0) >= $3`
			args = append(args, threshold)
		}
		rows, err := e.Store.DB.Query(
			`SELECT p.id, p.title, COALESCE(p.arxiv_id,''), p.read_status,
			        COALESCE(ar.skim_score, 0), COALESCE(ar.deep_dive_md,'') IS NOT NULL AND COALESCE(ar.deep_dive_md,'') != ''
			 FROM papers p
			 LEFT JOIN analysis_reports ar ON ar.paper_id = p.id
			 WHERE p.created_at >= $1 AND p.read_status != 'unread'`+scoreFilter+`
			 ORDER BY COALESCE(ar.skim_score,0) DESC, p.created_at DESC LIMIT $2`, args...)
		if err != nil {
			return nil
		}
		defer rows.Close()
		var out []briefPaper
		for rows.Next() {
			var p briefPaper
			var score float64
			if err := rows.Scan(&p.ID, &p.Title, &p.ArxivID, &p.ReadStatus, &score, &p.HasDeepRead); err != nil {
				continue
			}
			if score > 0 {
				s := score
				p.SkimScore = &s
			}
			out = append(out, p)
		}
		return out
	}
	papers := pick(todayStart, true, limit)
	seen := map[string]bool{}
	for _, p := range papers {
		seen[p.ID] = true
	}
	if len(papers) < limit {
		for _, p := range pick(weekStart, true, limit*2) {
			if !seen[p.ID] {
				papers = append(papers, p)
				seen[p.ID] = true
			}
		}
	}
	if len(papers) < limit {
		for _, p := range pick(weekStart, false, limit*2) {
			if !seen[p.ID] {
				papers = append(papers, p)
				seen[p.ID] = true
			}
		}
	}
	if len(papers) > limit {
		papers = papers[:limit]
	}
	// 补充 innovations/summary/topics
	for i := range papers {
		p := &papers[i]
		var insights []byte
		if err := e.Store.DB.QueryRow(
			`SELECT COALESCE(key_insights,'{}') FROM analysis_reports WHERE paper_id=$1`, p.ID,
		).Scan(&insights); err == nil {
			var m map[string]any
			if jsonUnmarshal(insights, &m) == nil {
				if list, ok := m["skim_innovations"].([]any); ok {
					for _, x := range list {
						p.Innovations = append(p.Innovations, stringOf(x))
					}
				}
			}
		}
		_ = e.Store.DB.QueryRow(
			`SELECT COALESCE(abstract,'') FROM papers WHERE id=$1`, p.ID,
		).Scan(&p.Summary)
		topicRows, err := e.Store.DB.Query(
			`SELECT t.name FROM paper_topics pt JOIN topic_subscriptions t ON t.id = pt.topic_id
			 WHERE pt.paper_id=$1`, p.ID)
		if err == nil {
			for topicRows.Next() {
				var name string
				if topicRows.Scan(&name) == nil {
					p.Topics = append(p.Topics, name)
				}
			}
			topicRows.Close()
		}
	}
	return papers
}

func jsonUnmarshal(b []byte, v any) error {
	if len(b) == 0 {
		return fmt.Errorf("empty")
	}
	return json.Unmarshal(b, v)
}

// ---------- 统计 / 热点 / AI 洞察 ----------

type todaySummary struct {
	TotalPapers, TodayNew, WeekNew int
}

func (e *HandlerEnv) TodaySummary() todaySummary {
	today := userTodayStartUTC()
	week := today.AddDate(0, 0, -7)
	var s todaySummary
	_ = e.Store.DB.QueryRow(`SELECT COUNT(*) FROM papers`).Scan(&s.TotalPapers)
	_ = e.Store.DB.QueryRow(
		`SELECT COUNT(*) FROM papers WHERE created_at >= $1`, today.Format("2006-01-02 15:04:05.000000")).Scan(&s.TodayNew)
	_ = e.Store.DB.QueryRow(
		`SELECT COUNT(*) FROM papers WHERE created_at >= $1`, week.Format("2006-01-02 15:04:05.000000")).Scan(&s.WeekNew)
	return s
}

type hotKeyword struct {
	Keyword string `json:"keyword"`
	Count   int    `json:"count"`
}

func (e *HandlerEnv) HotKeywords(days, topK int) []hotKeyword {
	cutoff := time.Now().UTC().AddDate(0, 0, -days).Format("2006-01-02 15:04:05.000000")
	rows, err := e.Store.DB.Query(
		`SELECT metadata FROM papers WHERE created_at >= $1 LIMIT 500`, cutoff)
	if err != nil {
		return nil
	}
	defer rows.Close()
	counts := map[string]int{}
	for rows.Next() {
		var raw []byte
		if rows.Scan(&raw) != nil {
			continue
		}
		var m map[string]any
		if json.Unmarshal(raw, &m) != nil {
			continue
		}
		if kws, ok := m["keywords"].([]any); ok {
			for _, k := range kws {
				if s := strings.ToLower(stringOf(k)); s != "" {
					counts[s]++
				}
			}
		}
		if cats, ok := m["categories"].([]any); ok {
			for _, c := range cats {
				if s := stringOf(c); s != "" {
					counts[s]++
				}
			}
		}
	}
	// top-K（无序 map → 排序截断）
	out := make([]hotKeyword, 0, topK)
	for kw, c := range counts {
		out = append(out, hotKeyword{kw, c})
	}
	for i := 0; i < len(out); i++ {
		for j := i + 1; j < len(out); j++ {
			if out[j].Count > out[i].Count {
				out[i], out[j] = out[j], out[i]
			}
		}
	}
	if len(out) > topK {
		out = out[:topK]
	}
	return out
}

func (e *HandlerEnv) generateAISummary(ctx context.Context, limit int) string {
	papers := e.selectPapersForBrief(limit)
	if len(papers) == 0 {
		return "今日暂无新论文"
	}
	var info []string
	for i, p := range papers {
		if i >= 15 {
			break
		}
		abstract := p.Summary
		if len(abstract) > 150 {
			abstract = abstract[:150]
		}
		line := "- " + p.Title
		if abstract != "" {
			line += "\n  摘要：" + abstract
		}
		info = append(info, line)
	}
	prompt := fmt.Sprintf(`请作为一位资深研究员，分析以下最新论文列表，用中文撰写今日研究简报的核心洞察（200-400 字）。

## 最新论文
%s

请按以下结构撰写：
1. **今日焦点**：最值得关注的 1-2 个研究方向
2. **技术亮点**：关键技术突破或方法创新
3. **趋势洞察**：这些论文反映的整体研究趋势
4. **建议关注**：推荐深入阅读的论文及原因
`, strings.Join(info, "\n"))
	res, err := e.Gateway.Chat(ctx, "deep", prompt, 1024)
	if err != nil {
		log.Printf("[brief] AI summary failed: %v", err)
		return fmt.Sprintf("今日新增 %d 篇论文，涵盖多个研究方向", len(papers))
	}
	out := res.Content
	if len(out) > 600 {
		out = out[:600]
	}
	return out
}

// ---------- HTML 渲染（简报邮件） ----------

var mdBoldRe = regexp.MustCompile(`\*\*(.+?)\*\*`)
var mdItalicRe = regexp.MustCompile(`\*(.+?)\*`)
var mdHeadingRe = regexp.MustCompile(`^#{1,3}\s+(.+)$`)
var mdOrderedRe = regexp.MustCompile(`^\d+\.\s+`)

// mdToHTML 轻量 Markdown → HTML（与 Python _md_to_html 语义对齐）。
func mdToHTML(text string) string {
	if text == "" {
		return ""
	}
	var b strings.Builder
	inUL := false
	closeUL := func() {
		if inUL {
			b.WriteString("</ul>")
			inUL = false
		}
	}
	inline := func(s string) string {
		s = mdBoldRe.ReplaceAllString(s, "<strong>$1</strong>")
		return mdItalicRe.ReplaceAllString(s, "<em>$1</em>")
	}
	for _, line := range strings.Split(text, "\n") {
		stripped := strings.TrimSpace(line)
		if stripped == "" {
			closeUL()
			continue
		}
		if m := mdHeadingRe.FindStringSubmatch(stripped); m != nil {
			closeUL()
			level := strings.Count(strings.SplitN(stripped, " ", 2)[0], "#")
			fmt.Fprintf(&b, "<h%d>%s</h%d>", level+2, inline(m[1]), level+2)
		} else if strings.HasPrefix(stripped, "-") {
			if !inUL {
				b.WriteString("<ul>")
				inUL = true
			}
			item := strings.TrimPrefix(stripped, "-")
			item = strings.TrimSpace(item)
			fmt.Fprintf(&b, "<li>%s</li>", inline(item))
		} else if mdOrderedRe.MatchString(stripped) {
			closeUL()
			item := mdOrderedRe.ReplaceAllString(stripped, "")
			fmt.Fprintf(&b, "<li>%s</li>", inline(item))
		} else {
			closeUL()
			fmt.Fprintf(&b, "<p>%s</p>", inline(stripped))
		}
	}
	closeUL()
	return b.String()
}

// renderBriefHTML 简报邮件 HTML（结构与 Python DAILY_TEMPLATE 对齐）。
func (e *HandlerEnv) renderBriefHTML(papers []briefPaper, sum todaySummary, aiSummary string, hot []hotKeyword, siteURL string) string {
	var b strings.Builder
	esc := html.EscapeString
	b.WriteString("<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"UTF-8\"><style>")
	b.WriteString("body{font-family:-apple-system,'Segoe UI',sans-serif;max-width:800px;margin:0 auto;padding:24px;color:#1a1a2e;background:#fafbfc}")
	b.WriteString("h1{font-size:26px;font-weight:800;background:linear-gradient(135deg,#6366f1,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}")
	b.WriteString(".subtitle{color:#666;font-size:14px;margin-bottom:28px}.stats{display:flex;gap:12px;margin-bottom:24px}")
	b.WriteString(".stat-card{flex:1;background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;text-align:center}")
	b.WriteString(".stat-num{font-size:24px;font-weight:800;color:#6366f1}.stat-label{font-size:12px;color:#9ca3af;margin-top:4px}")
	b.WriteString(".section-title{font-size:16px;font-weight:700;margin:24px 0 12px;border-bottom:1px dashed #c084fc;padding-bottom:6px}")
	b.WriteString(".paper-item{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:14px;margin-bottom:10px}")
	b.WriteString(".paper-title{font-weight:600;font-size:14px}.paper-title a{color:#1a1a2e;text-decoration:none}")
	b.WriteString(".paper-id{font-size:11px;color:#9ca3af;font-family:monospace;margin:4px 0}")
	b.WriteString(".paper-summary{font-size:13px;color:#6b7280;margin-top:8px;line-height:1.6}")
	b.WriteString(".score-badge{display:inline-block;border-radius:9999px;font-weight:800;font-size:11px;padding:3px 8px}")
	b.WriteString(".score-high{background:#dcfce7;color:#166534}.score-mid{background:#fef3c7;color:#924e0e}.score-low{background:#fee2e2;color:#991b1b}")
	b.WriteString(".innovation-tag{display:inline-block;background:#fef3c7;color:#78350f;border-radius:8px;padding:4px 10px;font-size:11px;margin:2px}")
	b.WriteString(".kw-tag{display:inline-block;background:#ede9fe;color:#6d28d9;border-radius:8px;padding:4px 10px;font-size:12px;margin:2px}")
	b.WriteString(".deep-card{background:#faf5ff;border:1px solid #e9d5ff;border-radius:12px;padding:14px;margin-bottom:10px}")
	b.WriteString(".btn{display:inline-block;padding:8px 16px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff!important;text-decoration:none;border-radius:8px;font-size:12px;font-weight:600;margin-top:8px}")
	b.WriteString(".footer{text-align:center;color:#9ca3af;font-size:12px;margin-top:48px;padding-top:20px;border-top:2px solid #e2e8f0}")
	b.WriteString(".ai-insight-box{background:#f0f9ff;border:1px solid #bae6fd;border-radius:12px;padding:14px;margin-bottom:16px}")
	b.WriteString(".ai-insight-title{font-weight:700;color:#0369a1}.ai-insight-content{font-size:13px;color:#334155;margin-top:8px;line-height:1.7;white-space:pre-wrap}")
	b.WriteString("</style></head><body>")
	b.WriteString("<h1>PaperMind 研究日报</h1>")
	fmt.Fprintf(&b, "<div class=\"subtitle\">%s · 由 AI 自动生成</div>", esc(userDateStr()))
	fmt.Fprintf(&b, "<div class=\"stats\"><div class=\"stat-card\"><div class=\"stat-num\">%d</div><div class=\"stat-label\">论文总量</div></div>"+
		"<div class=\"stat-card\"><div class=\"stat-num\">%d</div><div class=\"stat-label\">今日新增</div></div>"+
		"<div class=\"stat-card\"><div class=\"stat-num\">%d</div><div class=\"stat-label\">本周新增</div></div></div>",
		sum.TotalPapers, sum.TodayNew, sum.WeekNew)
	if aiSummary != "" {
		fmt.Fprintf(&b, "<div class=\"ai-insight-box\"><span class=\"ai-insight-title\">🤖 AI 核心洞察</span><div class=\"ai-insight-content\">%s</div></div>", esc(aiSummary))
	}
	if len(hot) > 0 {
		b.WriteString("<div class=\"section-title\">🔥 本周热点</div>")
		for _, kw := range hot {
			fmt.Fprintf(&b, "<span class=\"kw-tag\">%s <span style=\"opacity:0.7\">(%d)</span></span>", esc(kw.Keyword), kw.Count)
		}
	}
	scoreClass := func(s *float64) (string, string) {
		if s == nil {
			return "", ""
		}
		pct := int(*s * 100)
		cls := "score-mid"
		if *s >= 0.8 {
			cls = "score-high"
		} else if *s < 0.6 {
			cls = "score-low"
		}
		return cls, fmt.Sprintf("%d", pct)
	}
	// 分组
	groups := map[string][]briefPaper{}
	var order []string
	var uncategorized []briefPaper
	for _, p := range papers {
		if len(p.Topics) == 0 {
			uncategorized = append(uncategorized, p)
			continue
		}
		for _, t := range p.Topics {
			if _, ok := groups[t]; !ok {
				order = append(order, t)
			}
			groups[t] = append(groups[t], p)
		}
	}
	writeItem := func(p briefPaper) {
		cls, pct := scoreClass(p.SkimScore)
		b.WriteString("<div class=\"paper-item\">")
		fmt.Fprintf(&b, "<div class=\"paper-title\"><a href=\"%s/papers/%s\" target=\"_blank\">%s</a>", esc(siteURL), esc(p.ID), esc(p.Title))
		if pct != "" {
			fmt.Fprintf(&b, " <span class=\"score-badge %s\">%s</span>", cls, pct)
		}
		b.WriteString("</div>")
		fmt.Fprintf(&b, "<div class=\"paper-id\">arXiv: <a href=\"https://arxiv.org/abs/%s\">%s</a> · %s</div>", esc(p.ArxivID), esc(p.ArxivID), esc(p.ReadStatus))
		if len(p.Innovations) > 0 {
			b.WriteString("<div>")
			for i, inn := range p.Innovations {
				if i >= 3 {
					break
				}
				if len(inn) > 50 {
					inn = inn[:50]
				}
				fmt.Fprintf(&b, "<span class=\"innovation-tag\">%s</span>", esc(inn))
			}
			b.WriteString("</div>")
		}
		if p.Summary != "" {
			s := p.Summary
			if len(s) > 400 {
				s = s[:400]
			}
			fmt.Fprintf(&b, "<div class=\"paper-summary\">%s</div>", esc(s))
		}
		fmt.Fprintf(&b, "<a href=\"%s/papers/%s\" class=\"btn\" target=\"_blank\">阅读原文</a></div>", esc(siteURL), esc(p.ID))
	}
	for _, topic := range order {
		fmt.Fprintf(&b, "<div class=\"section-title\">📋 %s (%d篇)</div>", esc(topic), len(groups[topic]))
		for _, p := range groups[topic] {
			writeItem(p)
		}
	}
	if len(uncategorized) > 0 {
		b.WriteString("<div class=\"section-title\">📄 其他论文</div>")
		for _, p := range uncategorized {
			writeItem(p)
		}
	}
	fmt.Fprintf(&b, "<div class=\"footer\">PaperMind · AI 驱动的学术研究工作流平台<br><a href=\"%s\">%s</a></div></body></html>", esc(siteURL), esc(siteURL))
	return b.String()
}

// ---------- handlers ----------

// BuildDailyBrief 完整简报构建（HTML + 可选邮件），供 daily_brief_publish 与 daily_report 复用。
func (e *HandlerEnv) BuildDailyBrief(ctx context.Context, limit int) (html string, sum todaySummary) {
	if limit <= 0 {
		limit = 30
	}
	sum = e.TodaySummary()
	papers := e.selectPapersForBrief(limit)
	hot := e.HotKeywords(7, 10)
	ai := e.generateAISummary(ctx, 20)
	siteURL := envOr("SITE_URL", "http://localhost:3002")
	return e.renderBriefHTML(papers, sum, ai, hot, siteURL), sum
}

// briefRecipientFromConfig 无显式收件人时读 daily_report_configs。
func (e *HandlerEnv) briefRecipientFromConfig() string {
	var recipients sql.NullString
	var sendEmail bool
	err := e.Store.DB.QueryRow(
		`SELECT COALESCE(recipient_emails,''), COALESCE(send_email_report, false) FROM daily_report_configs LIMIT 1`,
	).Scan(&recipients, &sendEmail)
	if err != nil || !sendEmail || recipients.String == "" {
		return ""
	}
	parts := strings.Split(recipients.String, ",")
	if len(parts) > 0 {
		return strings.TrimSpace(parts[0])
	}
	return ""
}

// HandleDailyBriefPublish daily_brief_publish：生成简报 + 邮件（账本防重）→ save_generated_content proposal。
func HandleDailyBriefPublish(ctx context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	html, _ := e.BuildDailyBrief(ctx, 30)
	// HTML 文件落盘（与 Python save_brief_html 语义一致）
	briefRoot := envOr("BRIEF_OUTPUT_ROOT", "/app/data/briefs")
	_ = os.MkdirAll(briefRoot, 0o755)
	savedPath := fmt.Sprintf("%s/daily_brief_%s.html", briefRoot, time.Now().UTC().Format("20060102_150405"))
	_ = os.WriteFile(savedPath, []byte(html), 0o644)

	recipient, _ := task.Input["recipient"].(string)
	if recipient == "" {
		recipient = e.briefRecipientFromConfig()
	}
	emailSent := false
	if recipient != "" {
		effectKey := "brief_mail:" + recipient + ":" + userDateStr()
		if HasEffect(e.Store, effectKey) {
			log.Printf("[brief] 邮件今日已发送（账本命中），跳过: %s", recipient)
		} else if SendEmailHTML(e.SMTP, recipient, "PaperMind Daily Brief", html) {
			RegisterEffect(e.Store, effectKey, "mail_send", task.TaskID)
			emailSent = true
		}
	}
	metadata := map[string]any{
		"saved_path": savedPath, "email_sent": emailSent,
		"source": map[bool]string{true: "manual", false: "auto"}[recipient != ""],
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind": "save_generated_content", "content_type": "daily_brief",
			"title": "Daily Brief: " + userDateStr(), "markdown": html,
			"metadata_json": metadata,
		},
		"saved_path": savedPath, "email_sent": emailSent,
	}, nil
}

// HandleSendBriefEmailEffect send_brief_email：effect ledger 保护的唯一发送路径。
func HandleSendBriefEmailEffect(ctx context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	recipient, _ := task.Input["recipient"].(string)
	subject, _ := task.Input["subject"].(string)
	contentID, _ := task.Input["content_id"].(string)
	if subject == "" {
		subject = "PaperMind 每日简报"
	}
	if recipient == "" {
		return nil, fmt.Errorf("缺少 recipient")
	}
	effectKey := fmt.Sprintf("brief_mail:%s:%s", recipient, orDefault(contentID, subject))
	if HasEffect(e.Store, effectKey) {
		return map[string]any{"sent": false, "skipped": true, "effect_key": effectKey}, nil
	}
	htmlContent := ""
	if contentID != "" {
		_ = e.Store.DB.QueryRow(
			`SELECT COALESCE(markdown,'') FROM generated_contents WHERE id=$1`, contentID,
		).Scan(&htmlContent)
	}
	if !SendEmailHTML(e.SMTP, recipient, subject, htmlContent) {
		return map[string]any{
			"sent": false, "error": "SMTP 未配置或发送失败（账本未登记，可重试）", "effect_key": effectKey,
		}, nil
	}
	RegisterEffect(e.Store, effectKey, "mail_send", task.TaskID)
	return map[string]any{"sent": true, "effect_key": effectKey}, nil
}
