/**
 * 统一错误处理工具
 * @author Color2333
 */

/**
 * 错误类型
 */
export enum ErrorType {
  NETWORK = "network",
  VALIDATION = "validation",
  AUTH = "auth",
  NOT_FOUND = "not_found",
  SERVER = "server",
  UNKNOWN = "unknown",
}

/**
 * 应用错误类
 */
export class AppError extends Error {
  constructor(
    public type: ErrorType,
    message: string,
    public originalError?: unknown,
  ) {
    super(message);
    this.name = "AppError";
  }
}

/**
 * 错误信息映射
 */
const ERROR_MESSAGES: Record<ErrorType, string> = {
  [ErrorType.NETWORK]: "网络连接失败，请检查网络设置",
  [ErrorType.VALIDATION]: "输入数据格式不正确",
  [ErrorType.AUTH]: "身份验证失败，请重新登录",
  [ErrorType.NOT_FOUND]: "请求的资源不存在",
  [ErrorType.SERVER]: "服务器错误，请稍后重试",
  [ErrorType.UNKNOWN]: "未知错误，请稍后重试",
};

/**
 * 解析错误类型
 */
export function parseErrorType(error: unknown): ErrorType {
  if (error instanceof AppError) {
    return error.type;
  }

  if (error instanceof Error) {
    const message = error.message.toLowerCase();

    // 网络错误
    if (
      message.includes("network") ||
      message.includes("fetch") ||
      message.includes("connection")
    ) {
      return ErrorType.NETWORK;
    }

    // 验证错误
    if (
      message.includes("validation") ||
      message.includes("invalid") ||
      message.includes("格式")
    ) {
      return ErrorType.VALIDATION;
    }

    // 认证错误
    if (
      message.includes("unauthorized") ||
      message.includes("401") ||
      message.includes("token")
    ) {
      return ErrorType.AUTH;
    }

    // 404
    if (message.includes("404") || message.includes("not found")) {
      return ErrorType.NOT_FOUND;
    }

    // 服务器错误
    if (
      message.includes("500") ||
      message.includes("502") ||
      message.includes("503")
    ) {
      return ErrorType.SERVER;
    }
  }

  return ErrorType.UNKNOWN;
}

/**
 * 获取用户友好的错误信息
 */
export function getErrorMessage(error: unknown): string {
  const type = parseErrorType(error);

  // 如果是 AppError，直接返回其消息
  if (error instanceof AppError) {
    return error.message;
  }

  // 如果是普通 Error，尝试使用其消息
  if (error instanceof Error) {
    // 检查是否是特定的已知错误
    const message = error.message;

    // API 错误响应
    if (message.startsWith("{")) {
      try {
        const parsed = JSON.parse(message);
        if (parsed.detail) {
          return parsed.detail;
        }
        if (parsed.message) {
          return parsed.message;
        }
        if (parsed.error) {
          return parsed.error;
        }
      } catch {
        // JSON 解析失败，使用原始消息
      }
    }

    // 返回原始错误消息（如果比较短）
    if (message.length < 100) {
      return message;
    }
  }

  // 使用默认错误消息
  return ERROR_MESSAGES[type];
}

/**
 * 处理错误并返回用户友好的信息
 */
export function handleError(error: unknown): {
  type: ErrorType;
  message: string;
  originalError?: unknown;
} {
  const type = parseErrorType(error);
  const message = getErrorMessage(error);

  return {
    type,
    message,
    originalError: error instanceof Error ? error : undefined,
  };
}

/**
 * 创建错误处理器
 */
export function createErrorHandler(
  onError?: (error: { type: ErrorType; message: string }) => void,
) {
  return (error: unknown) => {
    const handled = handleError(error);
    console.error("[Error Handler]", handled);
    onError?.(handled);
    return handled;
  };
}

/**
 * 安全地执行异步函数，自动处理错误
 */
export async function safeAsync<T>(
  fn: () => Promise<T>,
  errorHandler?: (error: { type: ErrorType; message: string }) => void,
): Promise<T | null> {
  try {
    return await fn();
  } catch (error) {
    const handled = handleError(error);
    errorHandler?.(handled);
    return null;
  }
}

/**
 * 判断是否应该重试
 */
export function shouldRetry(error: unknown): boolean {
  const type = parseErrorType(error);
  return (
    type === ErrorType.NETWORK ||
    type === ErrorType.SERVER ||
    (error instanceof Error && error.message.includes("timeout"))
  );
}

/**
 * 重试装饰器
 */
export async function retryAsync<T>(
  fn: () => Promise<T>,
  maxRetries = 3,
  delayMs = 1000,
): Promise<T> {
  let lastError: unknown;

  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;

      if (!shouldRetry(error) || i === maxRetries - 1) {
        throw error;
      }

      // 等待后重试
      await new Promise((resolve) => setTimeout(resolve, delayMs * (i + 1)));
    }
  }

  throw lastError;
}
