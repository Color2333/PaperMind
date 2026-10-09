// 双语翻译（fast 模式）：pdftotext 分页分段 → 并发 LLM 翻译 → paper_translation proposal。
// layout 模式（pdf2zh 随 Python 退役）自动降级为 fast。
package core

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync"
)

// translateSegment 分段提取（翻译结果以 map 承载，形状与 Python segments 对齐）。
type translateSegment struct {
	ID         string
	Type       string
	Content    string
	PageNumber int
}

// extractSegmentsPDF 分页提取段落（pdftotext 按页，\f 分页符切分）。
func extractSegmentsPDF(pdfPath string, maxPages int) []translateSegment {
	if maxPages <= 0 {
		maxPages = 30
	}
	raw := extractPDFTextRaw(pdfPath, maxPages)
	if raw == "" {
		return nil
	}
	var segs []translateSegment
	idx := 0
	pages := strings.Split(raw, "\f")
	for pageNum, pageText := range pages {
		if pageNum >= maxPages {
			break
		}
		pageText = strings.TrimSpace(pageText)
		if pageText == "" {
			continue
		}
		for _, block := range strings.Split(pageText, "\n\n") {
			block = strings.TrimSpace(block)
			// pdftotext 保留单换行；段落按空行分——块内多行合并为一段
			block = strings.Join(strings.Fields(block), " ")
			if len(block) < 20 {
				continue
			}
			if len(block) > 2000 {
				block = block[:2000]
			}
			idx++
			segs = append(segs, translateSegment{
				ID: fmt.Sprintf("p-%d", idx), Type: "paragraph",
				Content: block, PageNumber: pageNum + 1,
			})
		}
	}
	return segs
}

// HandleTranslateBilingualPDF translate_bilingual_pdf：fast 分段翻译；
// mode=layout 降级 fast（pdf2zh 随 Python worker 退役）。
func HandleTranslateBilingualPDF(ctx context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	paperID, _ := task.Input["paper_id"].(string)
	targetLang, _ := task.Input["target_lang"].(string)
	if targetLang == "" {
		targetLang = "zh"
	}
	if paperID == "" {
		return nil, fmt.Errorf("缺少 paper_id")
	}
	var pdfPath string
	if err := e.Store.DB.QueryRow(
		`SELECT COALESCE(pdf_path,'') FROM papers WHERE id=$1`, paperID,
	).Scan(&pdfPath); err != nil || pdfPath == "" {
		return nil, fmt.Errorf("论文 %s 没有 PDF 文件", paperID)
	}
	if _, err := os.Stat(pdfPath); err != nil {
		return nil, fmt.Errorf("PDF 文件不存在: %s", pdfPath)
	}

	segs := extractSegmentsPDF(pdfPath, 30)
	if len(segs) == 0 {
		return nil, fmt.Errorf("PDF 无可提取文本")
	}
	// 并发翻译段落（5 workers）；单段失败留空不阻断
	results := make([]map[string]any, len(segs))
	sem := make(chan struct{}, 5)
	var wg sync.WaitGroup
	for i, seg := range segs {
		wg.Add(1)
		results[i] = map[string]any{
			"id": seg.ID, "type": seg.Type, "content": seg.Content,
			"pageNumber": seg.PageNumber,
		}
		go func(i int, seg translateSegment) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			prompt := fmt.Sprintf(
				"Translate the following academic text to %s.\nMaintain the academic tone and technical terminology.\n\nText:\n%s\n\nTranslation:",
				targetLang, seg.Content)
			res, err := e.Gateway.Chat(ctx, "deep", prompt, 2048)
			if err != nil {
				return
			}
			results[i]["translation"] = strings.TrimSpace(res.Content)
		}(i, seg)
	}
	wg.Wait()

	return map[string]any{
		"proposal": map[string]any{
			"kind": "paper_translation", "paper_id": paperID,
			"target_lang": targetLang, "mode": "fast",
			"segments":           results,
			"bilingual_pdf_path": nil,
		},
		"pdf_url": fmt.Sprintf("/translate/bilingual-pdf/%s", paperID),
	}, nil
}
