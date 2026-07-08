import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { paperApi } from "@/services/api";
import type { ReasoningChainResult } from "@/types";

type Toast = (type: ToastType, message: string) => void;

interface UseReasoningParams {
  id: string | undefined;
  toast: Toast;
  setReportTab: Dispatch<SetStateAction<string>>;
}

export function useReasoning({ id, toast, setReportTab }: UseReasoningParams) {
  const [reasoning, setReasoning] = useState<ReasoningChainResult | null>(null);
  const [reasoningLoading, setReasoningLoading] = useState(false);

  const handleReasoning = async () => {
    if (!id) return;
    setReasoningLoading(true);
    setReportTab("reasoning");
    try {
      const res = await paperApi.reasoningAnalysis(id);
      setReasoning(res.reasoning);
      toast("success", "推理链分析完成");
    } catch {
      toast("error", "推理链分析失败");
    } finally {
      setReasoningLoading(false);
    }
  };

  return {
    reasoning,
    setReasoning,
    reasoningLoading,
    setReasoningLoading,
    handleReasoning,
  };
}
