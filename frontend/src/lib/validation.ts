/**
 * 前端输入验证工具
 * @author Color2333
 */

/**
 * 验证结果
 */
export interface ValidationResult {
  valid: boolean;
  error?: string;
}

/**
 * 验证 ArXiv ID
 */
export function validateArxivId(arxivId: string): ValidationResult {
  if (!arxivId || typeof arxivId !== "string") {
    return { valid: false, error: "ArXiv ID 不能为空" };
  }

  const trimmed = arxivId.trim();
  if (!trimmed) {
    return { valid: false, error: "ArXiv ID 不能为空" };
  }

  // 基本格式检查：数字/年份.数字 或 数字/年份.数字
  const arxivPattern = /^\d{4}.\d{4,5}$/;
  const oldArxivPattern = /^[a-z-]+\/\d{7}$/;

  if (!arxivPattern.test(trimmed) && !oldArxivPattern.test(trimmed)) {
    return { valid: false, error: "ArXiv ID 格式不正确，应为：2301.12345 或 cs/1234567" };
  }

  return { valid: true };
}

/**
 * 验证主题名称
 */
export function validateTopicName(name: string): ValidationResult {
  if (!name || typeof name !== "string") {
    return { valid: false, error: "主题名称不能为空" };
  }

  const trimmed = name.trim();
  if (!trimmed) {
    return { valid: false, error: "主题名称不能为空" };
  }

  if (trimmed.length < 2) {
    return { valid: false, error: "主题名称至少需要 2 个字符" };
  }

  if (trimmed.length > 128) {
    return { valid: false, error: "主题名称不能超过 128 个字符" };
  }

  return { valid: true };
}

/**
 * 验证搜索查询
 */
export function validateSearchQuery(query: string): ValidationResult {
  if (!query || typeof query !== "string") {
    return { valid: false, error: "搜索关键词不能为空" };
  }

  const trimmed = query.trim();
  if (!trimmed) {
    return { valid: false, error: "搜索关键词不能为空" };
  }

  if (trimmed.length < 2) {
    return { valid: false, error: "搜索关键词至少需要 2 个字符" };
  }

  if (trimmed.length > 500) {
    return { valid: false, error: "搜索关键词不能超过 500 个字符" };
  }

  return { valid: true };
}

/**
 * 验证 LLM API Key
 */
export function validateApiKey(apiKey: string): ValidationResult {
  if (!apiKey || typeof apiKey !== "string") {
    return { valid: false, error: "API Key 不能为空" };
  }

  const trimmed = apiKey.trim();
  if (!trimmed) {
    return { valid: false, error: "API Key 不能为空" };
  }

  if (trimmed.length < 10) {
    return { valid: false, error: "API Key 长度不正确" };
  }

  return { valid: true };
}

/**
 * 验证邮箱地址
 */
export function validateEmail(email: string): ValidationResult {
  if (!email || typeof email !== "string") {
    return { valid: false, error: "邮箱不能为空" };
  }

  const trimmed = email.trim();
  if (!trimmed) {
    return { valid: false, error: "邮箱不能为空" };
  }

  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailPattern.test(trimmed)) {
    return { valid: false, error: "邮箱格式不正确" };
  }

  return { valid: true };
}

/**
 * 验证 URL
 */
export function validateUrl(url: string): ValidationResult {
  if (!url || typeof url !== "string") {
    return { valid: false, error: "URL 不能为空" };
  }

  const trimmed = url.trim();
  if (!trimmed) {
    return { valid: false, error: "URL 不能为空" };
  }

  try {
    new URL(trimmed);
    return { valid: true };
  } catch {
    return { valid: false, error: "URL 格式不正确" };
  }
}

/**
 * 验证数字范围
 */
export function validateNumberRange(
  value: number,
  min: number,
  max: number,
  fieldName = "数值",
): ValidationResult {
  if (typeof value !== "number" || isNaN(value)) {
    return { valid: false, error: `${fieldName}必须是有效的数字` };
  }

  if (value < min || value > max) {
    return { valid: false, error: `${fieldName}必须在 ${min} 到 ${max} 之间` };
  }

  return { valid: true };
}

/**
 * 通用字符串长度验证
 */
export function validateStringLength(
  value: string,
  minLength: number,
  maxLength: number,
  fieldName = "内容",
): ValidationResult {
  if (!value || typeof value !== "string") {
    return { valid: false, error: `${fieldName}不能为空` };
  }

  const trimmed = value.trim();
  if (trimmed.length < minLength) {
    return { valid: false, error: `${fieldName}至少需要 ${minLength} 个字符` };
  }

  if (trimmed.length > maxLength) {
    return { valid: false, error: `${fieldName}不能超过 ${maxLength} 个字符` };
  }

  return { valid: true };
}
