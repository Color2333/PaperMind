/**
 * 消息历史构建 Hook - 提取消息构建逻辑
 * @author Color2333
 */
import { useCallback } from "react";
import type { AgentMessage } from "@/services/api";
import type { ChatItem } from "@/contexts/AgentSessionContext";

/**
 * 将 ChatItem 转换为 AgentMessage
 */
export function useMessageHistory() {
  /**
   * 构建发送给 API 的消息历史
   */
  const buildMessageHistory = useCallback((items: ChatItem[]): AgentMessage[] => {
    const messages: AgentMessage[] = [];

    for (const item of items) {
      switch (item.type) {
        case "user":
          messages.push({ role: "user", content: item.content });
          break;

        case "assistant":
          messages.push({ role: "assistant", content: item.content });
          break;

        case "step_group":
          if (item.steps) {
            const summaries = item.steps
              .filter((s) => s.status === "done" || s.status === "error")
              .map(
                (s) =>
                  `[工具: ${s.toolName}] ${s.success ? "成功" : "失败"}: ${s.summary || ""}`,
              )
              .join("\n");
            if (summaries) {
              messages.push({
                role: "assistant",
                content: `执行了以下操作:\n${summaries}`,
              });
            }
          }
          break;

        case "action_confirm":
          messages.push({
            role: "assistant",
            content: `[等待确认] ${item.actionDescription || item.actionTool || ""}`,
          });
          break;

        case "artifact":
          messages.push({
            role: "assistant",
            content: `[已生成内容: ${item.artifactTitle || "未命名"}]\n${(item.artifactContent || "").slice(0, 500)}`,
          });
          break;

        case "error":
          messages.push({ role: "assistant", content: `[错误: ${item.content}]` });
          break;
      }
    }

    return messages;
  }, []);

  return { buildMessageHistory };
}
