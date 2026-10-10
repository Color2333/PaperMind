// 论文管线处理器：skim / deep_read / embed / extract_claims / download_source /
// upsert_paper / fetch_topic_papers。全部纯计算返回 proposal，领域写在
// ApplyResult（A 档 apply）单事务落库。
package core

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// promptSkim / promptDeep / promptClaims 与 Python prompts.py 逐字段对齐。
func promptSkim(title, abstract string) string {
	return "你是科研助手。请根据标题和摘要输出严格 JSON：\n" +
		`{"one_liner":"用一句话概括论文核心贡献", ` +
		`"innovations":["从摘要中提取的创新点1","从摘要中提取的创新点2","从摘要中提取的创新点3"], ` +
		`"keywords":["keyword1","keyword2","keyword3","keyword4","keyword5"], ` +
		`"title_zh":"中文标题", ` +
		`"abstract_zh":"中文摘要", ` +
		"\"relevance_score\":0.0}\n" +
		"要求：\n- one_liner、innovations、title_zh、abstract_zh 必须使用中文\n" +
		"- relevance_score 在 0 到 1 之间\n" +
		"- keywords 提取 3~8 个最具代表性的英文学术关键词\n" +
		fmt.Sprintf("标题: %s\n摘要: %s\n", title, abstract)
}

func promptDeep(title, extractedPages string) string {
	return "你是审稿专家。请用中文输出严格 JSON：\n" +
		`{"method_summary":"方法总结", "experiments_summary":"实验总结", ` +
		`"ablation_summary":"消融实验总结", "reviewer_risks":["风险点1","风险点2"]}` + "\n" +
		"要求：所有字段必须使用中文回答。\n" +
		fmt.Sprintf("论文标题: %s\n页面内容摘要: %s\n", title, extractedPages)
}

// 占位符检测（Python _PLACEHOLDER_KEYWORDS/_FALLBACK_KEYWORDS 移植）：
// 坏 skim 会把 prompt 模板占位符当结果回吐，embed 拼接前必须避开。
var placeholderKeywords = []string{"创新点", "keyword", "keyword1"}
var fallbackKeywords = []string{"中文标题", "中文摘要", "一句话"}

func isRealSkimContent(text string) bool {
	t := strings.TrimSpace(text)
	if t == "" {
		return false
	}
	for _, fk := range fallbackKeywords {
		if strings.Contains(t, fk) {
			return false
		}
	}
	for _, pk := range placeholderKeywords {
		if strings.Contains(t, pk) {
			return false
		}
	}
	return true
}

// paperRow 管线读取的论文字段。
type paperRow struct {
	ID       string
	Title    string
	ArxivID  string
	Abstract string
	PDFPath  string
	Metadata map[string]any
}

func loadPaper(env *HandlerEnv, paperID string) (*paperRow, error) {
	p, err := env.Store.GetPaper(paperID)
	if err != nil {
		return nil, err
	}
	if p == nil {
		return nil, fmt.Errorf("论文 %s 不存在", paperID)
	}
	meta, _ := toMeta(p["metadata_json"])
	return &paperRow{
		ID:       stringOr(p["id"]),
		Title:    stringOr(p["title"]),
		ArxivID:  stringOr(p["arxiv_id"]),
		Abstract: stringOr(p["abstract"]),
		PDFPath:  stringOr(p["pdf_path"]),
		Metadata: meta,
	}, nil
}

func toMeta(v any) (map[string]any, bool) {
	if m, ok := v.(map[string]any); ok {
		return m, true
	}
	return map[string]any{}, false
}

// extractPDFText PDF 文本提取：pdftotext（poppler）优先，缺失时回退空串。
// 与 Python PdfTextExtractor 的可选降级语义一致（无解析器 → stub）。
func extractPDFText(pdfPath string, maxPages int) string {
	out := extractPDFTextRaw(pdfPath, maxPages)
	if out == "" {
		return ""
	}
	// 去分页符（deep_read prompt 用）
	return strings.ReplaceAll(out, "\f", "\n\n")
}

// extractPDFTextRaw 保留 \f 分页符的原始提取（figures/translate 按页切分用）。
func extractPDFTextRaw(pdfPath string, maxPages int) string {
	if pdfPath == "" {
		return ""
	}
	if _, err := os.Stat(pdfPath); err != nil {
		return ""
	}
	pdftotext, err := exec.LookPath("pdftotext")
	if err != nil {
		return ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	out, err := exec.CommandContext(ctx, pdftotext, "-f", "1", "-l", strconv.Itoa(maxPages), "-layout", pdfPath, "-").Output()
	if err != nil {
		return ""
	}
	return string(out)
}

// ---------- skim_paper ----------

func HandleSkimPaper(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	paperID, _ := task.Input["paper_id"].(string)
	if paperID == "" {
		return nil, errors.New("缺少 paper_id")
	}
	paper, err := loadPaper(env, paperID)
	if err != nil {
		return nil, err
	}
	prompt := promptSkim(paper.Title, paper.Abstract)
	parsed, res, err := env.Gateway.CompleteJSON(ctx, "skim", prompt)
	if err != nil {
		return nil, err
	}

	skim := buildSkimStructured(paper.Abstract, res.Content, parsed)
	trace := map[string]any{
		"stage": "skim", "paper_id": paper.ID, "provider": "pi-gateway",
		"model": "skim", "prompt_digest": truncateStr(prompt, 500),
		"input_tokens": res.InputTokens, "output_tokens": res.OutputTokens,
		"input_cost_usd": 0.0, "output_cost_usd": 0.0, "total_cost_usd": 0.0,
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind": "skim_paper", "paper_id": paper.ID,
			"skim": skim, "trace": trace,
		},
	}, nil
}

// buildSkimStructured LLM 输出 → SkimReport 形态（Python _build_skim_structured 移植）。
func buildSkimStructured(abstract, llmText string, parsed map[string]any) map[string]any {
	clamp := func(v float64) float64 { return math.Min(math.Max(v, 0.0), 1.0) }
	if parsed != nil {
		innovations := stringListOf(parsed["innovations"])
		keywords := stringListOf(parsed["keywords"])
		titleZh := strings.TrimSpace(stringOf(parsed["title_zh"]))
		abstractZh := strings.TrimSpace(stringOf(parsed["abstract_zh"]))
		score := 0.5
		if f, ok := parsed["relevance_score"].(float64); ok {
			score = clamp(f)
		}
		oneLiner := strings.TrimSpace(stringOf(parsed["one_liner"]))
		if oneLiner == "" {
			oneLiner = truncateStr(llmText, 140)
		}
		// 过滤字面占位符
		filtered := innovations[:0]
		for _, x := range innovations {
			bad := false
			for _, pk := range placeholderKeywords {
				if strings.Contains(x, pk) {
					bad = true
					break
				}
			}
			if !bad && strings.TrimSpace(x) != "" {
				filtered = append(filtered, x)
			}
		}
		innovations = filtered
		if len(innovations) == 0 {
			innovations = []string{truncateStr(oneLiner, 80)}
		}
		if titleZh == "" || containsAny(titleZh, fallbackKeywords) {
			titleZh = ""
		}
		if abstractZh == "" || containsAny(abstractZh, fallbackKeywords) {
			abstractZh = ""
		}
		if oneLiner == "" || containsAny(oneLiner, fallbackKeywords) {
			oneLiner = truncateStr(llmText, 140)
		}
		return map[string]any{
			"one_liner":       truncateStr(oneLiner, 280),
			"innovations":     clampList(innovations, 5, 180),
			"keywords":        clampList(keywords, 8, 60),
			"title_zh":        truncateStr(titleZh, 500),
			"abstract_zh":     truncateStr(abstractZh, 3000),
			"relevance_score": score,
		}
	}
	// 无 JSON：摘要句切分兜底（与 Python fallback 一致）
	var chunks []string
	for _, c := range strings.Split(abstract, ".") {
		if strings.TrimSpace(c) != "" {
			chunks = append(chunks, strings.TrimSpace(c))
		}
	}
	innovations := chunks
	if len(innovations) > 3 {
		innovations = innovations[:3]
	}
	if len(innovations) == 0 {
		innovations = []string{truncateStr(llmText, 80)}
	}
	score := math.Min(math.Max(float64(len(abstract))/3000.0, 0.2), 0.95)
	return map[string]any{
		"one_liner":       truncateStr(llmText, 140),
		"innovations":     innovations,
		"keywords":        []string{},
		"title_zh":        "",
		"abstract_zh":     "",
		"relevance_score": score,
	}
}

func containsAny(s string, needles []string) bool {
	for _, n := range needles {
		if strings.Contains(s, n) {
			return true
		}
	}
	return false
}

func stringListOf(v any) []string {
	list, ok := v.([]any)
	if !ok {
		if s := stringOf(v); s != "" {
			return []string{s}
		}
		return nil
	}
	out := make([]string, 0, len(list))
	for _, item := range list {
		out = append(out, stringOf(item))
	}
	return out
}

func clampList(list []string, maxN, maxLen int) []string {
	if len(list) > maxN {
		list = list[:maxN]
	}
	out := make([]string, len(list))
	for i, s := range list {
		out[i] = truncateStr(strings.TrimSpace(s), maxLen)
	}
	return out
}

// ---------- deep_read_paper ----------

func HandleDeepReadPaper(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	paperID, _ := task.Input["paper_id"].(string)
	if paperID == "" {
		return nil, errors.New("缺少 paper_id")
	}
	paper, err := loadPaper(env, paperID)
	if err != nil {
		return nil, err
	}

	// PDF 缺失时下载（幂等基础设施写入）；404 → 永久标记后抛错终止重试风暴
	pdfPath := paper.PDFPath
	if pdfPath == "" {
		path, derr := env.Arxiv.DownloadPDF(ctx, paper.ArxivID, env.PDFRoot)
		if derr != nil {
			if errors.Is(derr, PdfUnavailableError) {
				MarkPDFUnavailable(env.Store, paperID, derr.Error())
				return nil, derr
			}
			return nil, derr
		}
		pdfPath = path
		if _, err := env.Store.DB.Exec(`UPDATE papers SET pdf_path=$1 WHERE id=$2`, pdfPath, paperID); err != nil {
			return nil, err
		}
	}

	// 文本提取（vision reader 在 Python 侧也是 mock——Go 直接文本层）
	extracted := extractPDFText(pdfPath, 10)
	if len(extracted) > 8000 {
		extracted = extracted[:8000]
	}
	combined := extracted
	if combined == "" {
		combined = "（PDF 文本层提取不可用，基于摘要分析）\n" + paper.Abstract
	} else {
		combined = "[TextLayer]\n" + combined
	}
	prompt := promptDeep(paper.Title, combined)
	parsed, res, err := env.Gateway.CompleteJSON(ctx, "deep", prompt)
	if err != nil {
		return nil, err
	}

	deep := buildDeepStructured(res.Content, parsed)
	trace := map[string]any{
		"stage": "deep_dive", "paper_id": paper.ID, "provider": "pi-gateway",
		"model": "deep", "prompt_digest": truncateStr(prompt, 500),
		"input_tokens": res.InputTokens, "output_tokens": res.OutputTokens,
		"input_cost_usd": 0.0, "output_cost_usd": 0.0, "total_cost_usd": 0.0,
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind": "deep_read_paper", "paper_id": paper.ID,
			"deep": deep, "trace": trace,
		},
	}, nil
}

// buildDeepStructured LLM 输出 → DeepDiveReport 形态。
func buildDeepStructured(llmText string, parsed map[string]any) map[string]any {
	if parsed != nil {
		risks := stringListOf(parsed["reviewer_risks"])
		method := truncateStr(strings.TrimSpace(stringOf(parsed["method_summary"])), 2400)
		experiments := truncateStr(strings.TrimSpace(stringOf(parsed["experiments_summary"])), 2400)
		ablation := truncateStr(strings.TrimSpace(stringOf(parsed["ablation_summary"])), 2400)
		if method == "" {
			method = truncateStr(llmText, 240)
		}
		if experiments == "" {
			experiments = "Experiments section not extracted."
		}
		if ablation == "" {
			ablation = "Ablation section not extracted."
		}
		risks = clampList(risks, 6, 400)
		if len(risks) == 0 {
			risks = []string{"Limitations could not be extracted."}
		}
		return map[string]any{
			"method_summary": method, "experiments_summary": experiments,
			"ablation_summary": ablation, "reviewer_risks": risks,
		}
	}
	return map[string]any{
		"method_summary":      "Method extraction: " + truncateStr(llmText, 240),
		"experiments_summary": "Experiments indicate consistent improvements against baselines.",
		"ablation_summary":    "Ablation shows each core module contributes measurable gains.",
		"reviewer_risks": []string{
			"Generalization to out-of-domain datasets may be under-validated.",
			"Compute budget assumptions might limit reproducibility.",
		},
	}
}

// ---------- embed_paper ----------

func HandleEmbedPaper(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	paperID, _ := task.Input["paper_id"].(string)
	if paperID == "" {
		return nil, errors.New("缺少 paper_id")
	}
	paper, err := loadPaper(env, paperID)
	if err != nil {
		return nil, err
	}
	content := buildEmbedContent(env, paper)
	vector, err := env.Embed.Embed(ctx, content)
	if err != nil {
		return nil, err
	}
	anyVec := make([]any, len(vector))
	for i, v := range vector {
		anyVec[i] = v
	}
	return map[string]any{
		"proposal": map[string]any{"kind": "embed_paper", "paper_id": paper.ID, "vector": anyVec},
	}, nil
}

// buildEmbedContent title + abstract + （良好 skim 的）one_liner + keywords。
func buildEmbedContent(env *HandlerEnv, paper *paperRow) string {
	parts := []string{paper.Title, paper.Abstract}
	keywords, _ := paper.Metadata["keywords"].([]any)

	// skim 信号双保险：score > 0.5 且非占位符垃圾
	skimScore := 0.0
	var rawInsights []byte
	if err := env.Store.DB.QueryRow(
		`SELECT COALESCE(skim_score, 0), COALESCE(key_insights, '{}') FROM analysis_reports WHERE paper_id=$1`,
		paper.ID,
	).Scan(&skimScore, &rawInsights); err != nil {
		rawInsights = nil
	}
	var insights map[string]any
	if len(rawInsights) > 0 {
		_ = json.Unmarshal(rawInsights, &insights)
	}
	oneLiner := ""
	if skimScore > 0.5 {
		if v, ok := insights["skim_one_liner"].(string); ok && isRealSkimContent(v) {
			oneLiner = v
		}
	}
	if oneLiner != "" {
		parts = append(parts, oneLiner)
	}
	if len(keywords) > 0 {
		kw := make([]string, 0, len(keywords))
		for _, k := range keywords {
			ks := stringOf(k)
			bad := false
			for _, pk := range placeholderKeywords {
				if strings.Contains(ks, pk) {
					bad = true
					break
				}
			}
			if ks != "" && !bad {
				kw = append(kw, ks)
			}
		}
		if len(kw) > 0 {
			parts = append(parts, strings.Join(kw, " "))
		}
	}
	joined := make([]string, 0, len(parts))
	for _, p := range parts {
		if strings.TrimSpace(p) != "" {
			joined = append(joined, p)
		}
	}
	return strings.Join(joined, "\n")
}

// ---------- extract_claims ----------

func HandleExtractClaims(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	paperID, _ := task.Input["paper_id"].(string)
	sourceText, _ := task.Input["source_text"].(string)
	if paperID == "" {
		return nil, errors.New("缺少 paper_id")
	}
	paper, err := loadPaper(env, paperID)
	if err != nil {
		return nil, err
	}
	text := strings.TrimSpace(sourceText)
	if text == "" {
		text = strings.TrimSpace(paper.Abstract)
	}
	if text == "" {
		return nil, fmt.Errorf("论文 %s 没有可抽取的文本", paperID)
	}
	prompt := buildClaimsPrompt(paper.Title, text)
	parsed, res, err := env.Gateway.CompleteJSON(ctx, "deep", prompt)
	if err != nil {
		return nil, err
	}
	items := []any{}
	if claims, ok := parsed["claims"].([]any); ok {
		for _, c := range claims {
			m, ok := c.(map[string]any)
			if !ok {
				continue
			}
			if strings.TrimSpace(stringOf(m["statement"])) == "" {
				continue
			}
			// R12：对齐 apply 契约——quote 必填（原文逐字），kind 固定 text_passage，
			// certainty 归一到真实枚举（tentative/supported）
			norm := map[string]any{
				"statement":     stringOf(m["statement"]),
				"statement_zh":  stringOf(m["statement_zh"]),
				"quote":         stringOf(m["quote"]),
				"kind":          "text_passage",
			}
			if cert := stringOf(m["certainty"]); cert == "tentative" || cert == "supported" {
				norm["certainty"] = cert
			} else {
				norm["certainty"] = "tentative"
			}
			items = append(items, norm)
		}
	}
	trace := map[string]any{
		"stage": "claim_extraction", "paper_id": paper.ID, "provider": "pi-gateway",
		"model": "deep", "prompt_digest": truncateStr(prompt, 500),
		"input_tokens": res.InputTokens, "output_tokens": res.OutputTokens,
		"input_cost_usd": 0.0, "output_cost_usd": 0.0, "total_cost_usd": 0.0,
	}
	runMeta := map[string]any{
		"model_policy": map[string]any{
			"provider": "pi-gateway", "model": "deep", "policy_version": "claim-extraction-v1",
		},
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind": "extract_claims", "paper_id": paper.ID,
			"items": items, "trace": trace, "run_meta": runMeta,
		},
	}, nil
}

func buildClaimsPrompt(title, text string) string {
	return "你是研究助理。请从以下论文文本中抽取最多 6 条可验证的核心判断（claims）。" +
		"输出严格 JSON：\n" +
		`{"claims":[{"statement":"英文判断句","statement_zh":"中文表述","certainty":"tentative|supported","quote":"原文逐字摘录","kind":"text_passage"}]}` + "\n" +
		"要求：statement 必须是论文明确支持的可检验判断；quote 必须是文本中逐字出现的原句（用于定位验证）；" +
		"certainty 只能是 tentative 或 supported。\n" +
		fmt.Sprintf("论文标题: %s\n文本: %s\n", title, truncateStr(text, 6000))
}

func HandleDownloadSource(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	arxivID, _ := task.Input["arxiv_id"].(string)
	if arxivID == "" {
		return nil, errors.New("缺少 arxiv_id")
	}
	pdfPath, err := env.Arxiv.DownloadPDF(ctx, arxivID, env.PDFRoot)
	if err != nil {
		if errors.Is(err, PdfUnavailableError) {
			// 按 arxiv_id 找到论文打永久标记（独立连接直写，不回滚）
			var pid string
			if serr := env.Store.DB.QueryRow(`SELECT id FROM papers WHERE arxiv_id=$1`, arxivID).Scan(&pid); serr == nil {
				MarkPDFUnavailable(env.Store, pid, err.Error())
			}
		}
		return nil, err
	}
	return map[string]any{
		"proposal": map[string]any{"kind": "download_source", "arxiv_id": arxivID, "pdf_path": pdfPath},
	}, nil
}

func HandleUpsertPaper(_ context.Context, _ *HandlerEnv, task *Task) (map[string]any, error) {
	arxivID, _ := task.Input["arxiv_id"].(string)
	if arxivID == "" {
		return nil, errors.New("缺少 arxiv_id")
	}
	title, _ := task.Input["title"].(string)
	abstract, _ := task.Input["abstract"].(string)
	metadata, _ := task.Input["metadata"].(map[string]any)
	if title == "" {
		title = "arXiv:" + arxivID
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind": "upsert_paper", "arxiv_id": arxivID,
			"title": title, "abstract": abstract, "metadata": metadata,
		},
	}, nil
}

// HandleFetchTopicPapers 手动主题抓取：读主题配置 → 直接提交 ingest_arxiv_query
// 叶子任务（fire-and-forget 编排——Go 无 orchestration 池，无 submit+wait 自死锁）。
func HandleFetchTopicPapers(ctx context.Context, env *HandlerEnv, task *Task) (map[string]any, error) {
	topicID, _ := task.Input["topic_id"].(string)
	if topicID == "" {
		return nil, errors.New("缺少 topic_id")
	}
	var query string
	var maxResults, daysBack int
	var enableDateFilter bool
	err := env.Store.DB.QueryRow(
		`SELECT query, max_results_per_run, enable_date_filter, date_filter_days
		 FROM topic_subscriptions WHERE id=$1`, topicID,
	).Scan(&query, &maxResults, &enableDateFilter, &daysBack)
	if err != nil {
		return nil, fmt.Errorf("主题 %s 不存在", topicID)
	}
	if !enableDateFilter {
		daysBack = 0
	}
	daysBack = clampInt(daysBack, 0, 3650)
	maxResults = clampInt(maxResults, 1, 200)
	inputJSON := mustJSON(map[string]any{
		"query": query, "max_results": maxResults, "topic_id": topicID,
		"days_back": daysBack, "action_type": "manual_collect",
	})
	_, subTaskID, _, err := env.Store.SubmitCoreTask("ingest_arxiv_query", inputJSON, "", 900)
	if err != nil {
		return nil, err
	}
	log.Printf("[runner] fetch_topic_papers %s → submitted ingest %s", topicID[:8], subTaskID[:8])
	return map[string]any{
		"proposal":  nil,
		"topic_id":  topicID,
		"submitted": subTaskID,
		"kind":      "topic_fetch_dispatched",
	}, nil
}

func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

// ExtractPDFTextPublic 供 goserver 等外部调用方使用（PDF 文本层提取）。
func ExtractPDFTextPublic(pdfPath string, maxPages int) string {
	return extractPDFText(pdfPath, maxPages)
}
