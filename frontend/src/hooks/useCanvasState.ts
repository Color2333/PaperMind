/**
 * Canvas 状态管理 Hook
 * @author Color2333
 */
import { useState, useCallback } from "react";
import type { CanvasData } from "@/contexts/AgentSessionContext";

export function useCanvasState() {
  const [canvas, setCanvas] = useState<CanvasData | null>(null);

  /**
   * 更新 Canvas 内容
   */
  const updateCanvas = useCallback((data: CanvasData | null) => {
    setCanvas(data);
  }, []);

  /**
   * 清空 Canvas
   */
  const clearCanvas = useCallback(() => {
    setCanvas(null);
  }, []);

  /**
   * 显示 Markdown 内容
   */
  const showMarkdown = useCallback((title: string, markdown: string) => {
    setCanvas({ title, markdown, isHtml: false });
  }, []);

  /**
   * 显示 HTML 内容
   */
  const showHtml = useCallback((title: string, html: string) => {
    setCanvas({ title, markdown: html, isHtml: true });
  }, []);

  return {
    canvas,
    setCanvas: updateCanvas,
    clearCanvas,
    showMarkdown,
    showHtml,
  };
}
