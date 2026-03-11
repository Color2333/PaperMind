/**
 * SSE 流处理 Hook - 提取流式处理的公共逻辑
 * @author Color2333
 */
import { useRef, useCallback, useEffect } from "react";
import type { SSEEvent, SSEEventType } from "@/types";

export interface StreamBuffer {
  current: string;
  rafId: number | null;
}

export interface UseSSEStreamOptions {
  onEvent: (event: SSEEvent) => void;
  onComplete?: () => void;
  onError?: (error: Error) => void;
}

/**
 * SSE 流缓冲管理
 */
export function useStreamBuffer() {
  const bufferRef = useRef<StreamBuffer>({
    current: "",
    rafId: null,
  });

  const drainBuffer = useCallback((): string => {
    const { rafId, current } = bufferRef.current;
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      bufferRef.current.rafId = null;
    }
    const text = current;
    bufferRef.current.current = "";
    return text;
  }, []);

  const flushBuffer = useCallback((setter: (text: string) => void) => {
    const text = bufferRef.current.current;
    if (!text) return;
    bufferRef.current.current = "";
    setter(text);
  }, []);

  const scheduleFlush = useCallback((setter: (text: string) => void) => {
    if (bufferRef.current.rafId !== null) return;
    bufferRef.current.rafId = requestAnimationFrame(() => {
      bufferRef.current.rafId = null;
      flushBuffer(setter);
    });
  }, [flushBuffer]);

  const appendText = useCallback((text: string) => {
    bufferRef.current.current += text;
  }, []);

  return {
    bufferRef,
    drainBuffer,
    flushBuffer,
    scheduleFlush,
    appendText,
  };
}

/**
 * SSE 流解析和处理
 */
export function useSSEStream(options: UseSSEStreamOptions) {
  const abortControllerRef = useRef<AbortController | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  const cancelStream = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => cancelStream();
  }, [cancelStream]);

  const startStream = useCallback(
    (reader: ReadableStreamDefaultReader<Uint8Array>, signal?: AbortSignal) => {
      const parseSSEStream = async () => {
        const decoder = new TextDecoder();
        let buffer = "";
        let currentEvent = "";

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
              if (line.startsWith("event: ")) {
                currentEvent = line.slice(7).trim();
              } else if (line.startsWith("data: ")) {
                const dataStr = line.slice(6);
                try {
                  const data = JSON.parse(dataStr);
                  optionsRef.current.onEvent({ type: currentEvent as SSEEventType, data });
                } catch (e) {
                  console.warn("[SSE] Failed to parse:", currentEvent, dataStr.slice(0, 200), e);
                }
                currentEvent = "";
              }
              // 空行 = 事件结束，重置状态
              if (line === "") {
                currentEvent = "";
              }
            }
          }
          // 流结束时处理残余数据
          if (buffer.trim()) {
            buffer += "\n";
            const remaining = buffer.split("\n");
            for (const line of remaining) {
              if (line.startsWith("event: ")) {
                currentEvent = line.slice(7).trim();
              } else if (line.startsWith("data: ")) {
                const dataStr = line.slice(6);
                try {
                  const data = JSON.parse(dataStr);
                  optionsRef.current.onEvent({ type: currentEvent as SSEEventType, data });
                } catch { /* ignore trailing incomplete data */ }
                currentEvent = "";
              }
            }
          }
          optionsRef.current.onComplete?.();
        } catch (error) {
          if (error instanceof Error && error.name !== "AbortError") {
            optionsRef.current.onError?.(error);
          }
        }
      };

      parseSSEStream();

      if (signal) {
        signal.addEventListener("abort", () => {
          reader.cancel().catch(() => {});
        });
      }
    },
    [], // 通过 optionsRef 解耦，无需依赖外部变量
  );

  return {
    abortControllerRef,
    cancelStream,
    startStream,
  };
}
