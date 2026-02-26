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

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
              if (!line.trim()) continue;
              const [eventLine, dataLine] = line.split("\n");
              if (!eventLine || !dataLine) continue;

              const eventType = eventLine.replace("event: ", "").trim() as SSEEventType;
              const dataStr = dataLine.replace("data: ", "").trim();

              try {
                const data = JSON.parse(dataStr);
                options.onEvent({ type: eventType, data });
              } catch (e) {
                console.error("Failed to parse SSE data:", e);
              }
            }
          }
          options.onComplete?.();
        } catch (error) {
          if (error instanceof Error && error.name !== "AbortError") {
            options.onError?.(error);
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
    [options],
  );

  return {
    abortControllerRef,
    cancelStream,
    startStream,
  };
}
