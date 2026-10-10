// SMTP 邮件 + 副作用账本（effect ledger）+ 网关视觉调用。
package core

import (
	"context"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/smtp"
	"strings"
	"time"
)

// SMTPConfig 从环境读取（与 Python settings 同名 env：SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/SMTP_FROM）。
type SMTPConfig struct {
	Host     string
	Port     string
	User     string
	Password string
	From     string
}

// LoadSMTPConfig 环境缺任一关键字段返回 nil（调用方按"未配置"处理）。
func LoadSMTPConfig() *SMTPConfig {
	host := envOr("SMTP_HOST", "")
	user := envOr("SMTP_USER", "")
	pass := envOr("SMTP_PASSWORD", "")
	if host == "" || user == "" || pass == "" {
		return nil
	}
	return &SMTPConfig{
		Host: host, Port: envOr("SMTP_PORT", "587"),
		User: user, Password: pass, From: envOr("SMTP_FROM", user),
	}
}

// SendEmailHTML 发送 HTML 邮件（STARTTLS，与 Python smtplib 语义对齐）。
// 未配置或发送失败返回 false（调用方不登记账本，可重试）。
func SendEmailHTML(cfg *SMTPConfig, recipient, subject, html string) bool {
	if cfg == nil {
		return false
	}
	from := cfg.From
	to := recipient
	boundary := "pm-boundary-" + newCoreID()[:16]
	headers := fmt.Sprintf(
		"From: %s\r\nTo: %s\r\nSubject: %s\r\nDate: %s\r\nMIME-Version: 1.0\r\n"+
			"Content-Type: multipart/alternative; boundary=\"%s\"\r\n\r\n",
		from, to, mime.QEncoding.Encode("utf-8", subject),
		time.Now().Format(time.RFC1123Z), boundary)
	body := fmt.Sprintf(
		"--%s\r\nContent-Type: text/html; charset=\"utf-8\"\r\nContent-Transfer-Encoding: base64\r\n\r\n%s\r\n--%s--\r\n",
		boundary, base64.StdEncoding.EncodeToString([]byte(html)), boundary)

	addr := cfg.Host + ":" + cfg.Port
	var client *smtp.Client
	var err error
	if conn, derr := tls.Dial("tcp", addr, &tls.Config{ServerName: cfg.Host}); derr == nil {
		client, err = smtp.NewClient(conn, cfg.Host)
	} else {
		// 465 直连失败 → 587 STARTTLS
		client, err = smtp.Dial(addr)
		if err == nil {
			if ok, _ := client.Extension("STARTTLS"); ok {
				if err = client.StartTLS(&tls.Config{ServerName: cfg.Host}); err != nil {
					client.Close()
					return false
				}
			}
		}
	}
	if err != nil {
		return false
	}
	defer client.Close()
	if ok, _ := client.Extension("AUTH"); ok {
		auth := smtp.PlainAuth("", cfg.User, cfg.Password, cfg.Host)
		if err = client.Auth(auth); err != nil {
			return false
		}
	}
	if err = client.Mail(from); err != nil {
		return false
	}
	if err = client.Rcpt(to); err != nil {
		return false
	}
	w, err := client.Data()
	if err != nil {
		return false
	}
	if _, err = w.Write([]byte(headers + body)); err != nil {
		w.Close()
		return false
	}
	if err = w.Close(); err != nil {
		return false
	}
	return client.Quit() == nil
}

// ---------- 副作用账本（task_effects）----------

// HasEffect 幂等键是否已登记。
func HasEffect(store *CoreStore, effectKey string) bool {
	var one string
	return store.DB.QueryRow(
		`SELECT effect_key FROM task_effects WHERE effect_key=$1`, effectKey).Scan(&one) == nil
}

// RegisterEffect 登记副作用（唯一约束兜底并发；已存在返回 false）。
// R13：task_effects.task_id 外键指向旧 tasks.id(32)——core_tasks 的 36 位 UUID
// 写入必然 FK 失败且被忽略，导致邮件去重键永不登记。改为不关联旧执行体系，
// 幂等键本身已足够去重。
func RegisterEffect(store *CoreStore, effectKey, kind string, taskID string) bool {
	if HasEffect(store, effectKey) {
		return false
	}
	_, err := store.DB.Exec(
		`INSERT INTO task_effects (id, effect_key, kind, payload, committed_at)
		 VALUES ($1, $2, $3, '{}', $4)`,
		newCoreID(), effectKey, kind, nowParam())
	return err == nil
}

// ---------- 网关视觉调用 ----------

// ChatVision 多模态解读（OpenAI 兼容 image_url data URL）。
func (g *GatewayClient) ChatVision(ctx context.Context, model, prompt, imageBase64, mimeType string, maxTokens int) (*gatewayChatResult, error) {
	if mimeType == "" {
		mimeType = "image/png"
	}
	if maxTokens <= 0 {
		maxTokens = 1024
	}
	body := map[string]any{
		"model": model,
		"messages": []map[string]any{{
			"role": "user",
			"content": []map[string]any{
				{"type": "text", "text": prompt},
				{"type": "image_url", "image_url": map[string]string{
					"url": "data:" + mimeType + ";base64," + imageBase64,
				}},
			},
		}},
		"max_tokens": maxTokens,
	}
	payload, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, g.baseURL+"/v1/chat/completions", strings.NewReader(string(payload)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+g.token)
	resp, err := g.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("gateway %d: %s", resp.StatusCode, truncateStr(string(raw), 300))
	}
	var parsed struct {
		Choices []struct {
			Message struct {
				Content          string `json:"content"`
				ReasoningContent string `json:"reasoning_content"`
			} `json:"message"`
		} `json:"choices"`
		Usage struct {
			PromptTokens     int `json:"prompt_tokens"`
			CompletionTokens int `json:"completion_tokens"`
		} `json:"usage"`
	}
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return nil, fmt.Errorf("gateway 响应解析失败: %w", err)
	}
	if len(parsed.Choices) == 0 {
		return nil, fmt.Errorf("gateway 返回空 choices")
	}
	return &gatewayChatResult{
		Content:      parsed.Choices[0].Message.Content,
		InputTokens:  parsed.Usage.PromptTokens,
		OutputTokens: parsed.Usage.CompletionTokens,
	}, nil
}
