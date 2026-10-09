// 图表分析：pdfimages 提取嵌入图 → 视觉模型解读 → figure_analyses proposal。
// 布局兜底：无嵌入图时对含 "Figure N / Table N" 文本的页面整页渲染（pdftoppm）。
package core

import (
	"context"
	"encoding/base64"
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
) // extractedFigure 单张提取图（与 Python ExtractedFigure 对齐）。
type extractedFigure struct {
	PageNumber int
	ImageIndex int
	Bytes      []byte
	ImageType  string // figure / table
	Caption    string
}

var captionRe = regexp.MustCompile(`(?i)(figure|fig\.|table)\s*(\d+)[:.\s]*([^\n]{0,120})`)
var hasFigureRe = regexp.MustCompile(`(?i)(figure\s*\d|fig\.\s*\d|table\s*\d|tab\.\s*\d)`)

// extractFiguresPoppler pdfimages -png -p 提取嵌入图（文件名含页码）。
func extractFiguresPoppler(pdfPath string, maxFigures int) []extractedFigure {
	bin, err := exec.LookPath("pdfimages")
	if err != nil {
		return nil
	}
	tmpDir, err := os.MkdirTemp("", "pm-figs")
	if err != nil {
		return nil
	}
	defer os.RemoveAll(tmpDir)
	prefix := filepath.Join(tmpDir, "img")
	cmd := exec.Command(bin, "-png", "-p", pdfPath, prefix)
	if err := cmd.Run(); err != nil {
		return nil
	}
	entries, _ := os.ReadDir(tmpDir)
	var figs []extractedFigure
	for _, entry := range entries {
		if len(figs) >= maxFigures {
			break
		}
		name := entry.Name()
		if !strings.HasSuffix(name, ".png") {
			continue
		}
		// 文件名形如 img-002-000.png（页码-序号）
		parts := strings.Split(strings.TrimSuffix(name, ".png"), "-")
		if len(parts) < 3 {
			continue
		}
		pageNum, err1 := strconv.Atoi(parts[len(parts)-2])
		imgIdx, err2 := strconv.Atoi(parts[len(parts)-1])
		if err1 != nil || err2 != nil {
			continue
		}
		data, err := os.ReadFile(filepath.Join(tmpDir, name))
		if err != nil || len(data) < 2000 { // 过滤 icon/logo（<2KB）
			continue
		}
		// 尺寸过滤：PNG 头宽高（IHDR）
		if len(data) > 24 {
			w := int(data[16])<<24 | int(data[17])<<16 | int(data[18])<<8 | int(data[19])
			h := int(data[20])<<24 | int(data[21])<<16 | int(data[22])<<8 | int(data[23])
			if w < 100 || h < 80 {
				continue
			}
		}
		figs = append(figs, extractedFigure{
			PageNumber: pageNum, ImageIndex: imgIdx, Bytes: data,
			ImageType: "figure",
		})
	}
	return figs
}

// extractPageRenders 兜底：渲染含图表关键词的页面整页图。
func extractPageRenders(pdfPath, textLayer string, maxPages int) []extractedFigure {
	bin, err := exec.LookPath("pdftoppm")
	if err != nil {
		return nil
	}
	tmpDir, err := os.MkdirTemp("", "pm-pages")
	if err != nil {
		return nil
	}
	defer os.RemoveAll(tmpDir)
	// 找出含图表关键词的页（文本层按 \f 分页）
	var targetPages []string
	pages := strings.Split(textLayer, "\f")
	for i, pageText := range pages {
		if len(targetPages) >= maxPages {
			break
		}
		if hasFigureRe.MatchString(strings.ToLower(pageText)) {
			targetPages = append(targetPages, strconv.Itoa(i+1))
		}
	}
	if len(targetPages) == 0 {
		return nil
	}
	prefix := filepath.Join(tmpDir, "page")
	args := append([]string{"-png", "-r", "100", "-f", targetPages[0], "-l", targetPages[len(targetPages)-1]}, pdfPath, prefix)
	if err := exec.Command(bin, args...).Run(); err != nil {
		return nil
	}
	entries, _ := os.ReadDir(tmpDir)
	var figs []extractedFigure
	for i, entry := range entries {
		if i >= maxPages {
			break
		}
		if !strings.HasSuffix(entry.Name(), ".png") {
			continue
		}
		data, err := os.ReadFile(filepath.Join(tmpDir, entry.Name()))
		if err != nil {
			continue
		}
		figs = append(figs, extractedFigure{
			PageNumber: i + 1, ImageIndex: 0, Bytes: data,
			ImageType: "figure",
		})
	}
	return figs
}

// visionPrompts 与 Python VISION_PROMPT_FIGURE/TABLE 对齐。
func visionPrompt(imageType string, page int, caption string) string {
	captionHint := "未检测到标题"
	if caption != "" {
		captionHint = "图表标题: " + caption
	}
	if imageType == "table" {
		return fmt.Sprintf(`你是一个学术论文表格解读专家。请仔细分析这张表格图片，它来自一篇学术论文的第 %d 页。

请提供以下内容（中文回答）：
1. **表格内容**：表格展示了什么数据/对比
2. **关键发现**：最重要的数据点和结论
3. **对比分析**：不同方法/模型之间的性能差异
4. **最优结果**：表中最好的结果是什么，用什么方法达到的

%s

请用简洁专业的语言回答，使用 Markdown 格式。`, page, captionHint)
	}
	return fmt.Sprintf(`你是一个学术论文图表解读专家。请仔细分析这张图片，它来自一篇学术论文的第 %d 页。

请提供以下内容（中文回答）：
1. **图表类型**：这是什么类型的图表（架构图/流程图/折线图/柱状图/表格/公式/示意图等）
2. **核心内容**：图表展示了什么信息，主要结论是什么
3. **关键数据**：如果有数据，提取关键数值和趋势
4. **方法解读**：如果是架构图或流程图，描述各模块的作用和数据流向
5. **学术意义**：这张图在论文中可能的作用和重要性

%s

请用简洁专业的语言回答，使用 Markdown 格式。`, page, captionHint)
}

var mdFenceRe = regexp.MustCompile("(?s)```[a-zA-Z]*\\n?(.*?)```")

func cleanMarkdownFences(s string) string {
	if m := mdFenceRe.FindStringSubmatch(s); m != nil {
		return strings.TrimSpace(m[1])
	}
	return strings.TrimSpace(s)
}

// HandleAnalyzeFigures analyze_figures：提取 + 解读 + 图片落盘 + figure_analyses proposal。
func HandleAnalyzeFigures(ctx context.Context, e *HandlerEnv, task *Task) (map[string]any, error) {
	paperID, _ := task.Input["paper_id"].(string)
	maxFigures := intOf(task.Input["max_figures"], 12)
	if paperID == "" {
		return nil, fmt.Errorf("缺少 paper_id")
	}
	var pdfPath, title string
	if err := e.Store.DB.QueryRow(
		`SELECT COALESCE(pdf_path,''), COALESCE(title,'') FROM papers WHERE id=$1`, paperID,
	).Scan(&pdfPath, &title); err != nil || pdfPath == "" {
		return nil, fmt.Errorf("论文 %s 没有 PDF 文件", paperID)
	}
	if _, err := os.Stat(pdfPath); err != nil {
		return nil, fmt.Errorf("PDF 文件不存在: %s", pdfPath)
	}

	figs := extractFiguresPoppler(pdfPath, maxFigures)
	if len(figs) == 0 {
		textLayer := extractPDFText(pdfPath, 20)
		figs = extractPageRenders(pdfPath, textLayer, maxFigures)
	}
	if len(figs) == 0 {
		log.Printf("[figures] 论文 %s 未提取到图表", paperID[:8])
		return map[string]any{
			"proposal": map[string]any{
				"kind": "figure_analyses", "paper_id": paperID, "analyses": []any{},
			},
			"paper_id": paperID, "count": 0, "title": truncateStr(title, 30),
		}, nil
	}

	// caption 填充（文本层匹配）
	textLayer := extractPDFText(pdfPath, 20)
	for i := range figs {
		if m := captionRe.FindStringSubmatch(textLayer); m != nil && figs[i].Caption == "" {
			figs[i].Caption = strings.TrimSpace(m[0])
		}
		if hasFigureRe.MatchString(strings.ToLower(figs[i].Caption)) &&
			strings.HasPrefix(strings.ToLower(figs[i].Caption), "table") {
			figs[i].ImageType = "table"
		}
	}

	// 图片落盘（文件 IO 不属领域状态）
	figDir := filepath.Join(e.PDFRoot, "figures", paperID)
	_ = os.MkdirAll(figDir, 0o755)

	// 并发视觉解读（3 workers，与 Python 一致）
	type result struct {
		idx  int
		desc string
		err  error
	}
	results := make([]result, len(figs))
	sem := make(chan struct{}, 3)
	var wg sync.WaitGroup
	for i, fig := range figs {
		wg.Add(1)
		go func(i int, fig extractedFigure) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			b64 := base64.StdEncoding.EncodeToString(fig.Bytes)
			res, err := e.Gateway.ChatVision(ctx, "skim", visionPrompt(fig.ImageType, fig.PageNumber, fig.Caption), b64, "image/png", 1024)
			if err != nil {
				results[i] = result{i, "", err}
				return
			}
			results[i] = result{i, cleanMarkdownFences(res.Content), nil}
		}(i, fig)
	}
	wg.Wait()

	analyses := []any{}
	for i, r := range results {
		if r.err != nil {
			log.Printf("[figures] 页 %d 解读失败: %v", figs[i].PageNumber, r.err)
			continue
		}
		fig := figs[i]
		imgPath := filepath.Join(figDir, fmt.Sprintf("p%d_i%d.png", fig.PageNumber, fig.ImageIndex))
		if err := os.WriteFile(imgPath, fig.Bytes, 0o644); err != nil {
			continue
		}
		var captionAny any
		if fig.Caption != "" {
			captionAny = fig.Caption
		}
		analyses = append(analyses, map[string]any{
			"page_number": fig.PageNumber, "image_index": fig.ImageIndex,
			"image_type": fig.ImageType, "caption": captionAny,
			"description": r.desc, "image_path": imgPath,
			"bbox_json": nil,
		})
	}
	return map[string]any{
		"proposal": map[string]any{
			"kind": "figure_analyses", "paper_id": paperID, "analyses": analyses,
		},
		"paper_id": paperID, "count": len(analyses), "title": truncateStr(title, 30),
	}, nil
}
