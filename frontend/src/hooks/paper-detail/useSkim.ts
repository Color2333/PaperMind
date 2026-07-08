import { useState, useRef, useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { paperApi, pipelineApi } from "@/services/api";
import type { Paper, SkimReport } from "@/types";

type Toast = (type: ToastType, message: string) => void;

interface UseSkimParams {
  id: string | undefined;
  toast: Toast;
  setReportTab: Dispatch<SetStateAction<string>>;
  setPaper: Dispatch<SetStateAction<Paper | null>>;
}

export function useSkim({ id, toast, setReportTab, setPaper }: UseSkimParams) {
  const [skimReport, setSkimReport] = useState<SkimReport | null>(null);
  const [savedSkim, setSavedSkim] = useState<{
    summary_md: string;
    skim_score: number | null;
    key_insights: Record<string, unknown>;
  } | null>(null);
  const [skimLoading, setSkimLoading] = useState(false);
  const skimAbort = useRef<AbortController | null>(null);

  const handleSkim = async () => {
    if (!id) return;
    setSkimLoading(true);
    setReportTab("skim");
    try {
      const report = await pipelineApi.skim(id);
      setSkimReport(report);
      // 刷新论文信息，更新粗读报告
      const updated = await paperApi.detail(id);
      setPaper(updated);
      if (updated.skim_report) setSavedSkim(updated.skim_report);
      toast("success", "粗读完成");
    } catch {
      toast("error", "粗读失败");
    } finally {
      setSkimLoading(false);
    }
  };

  return {
    skimReport,
    setSkimReport,
    savedSkim,
    setSavedSkim,
    skimLoading,
    setSkimLoading,
    skimAbort,
    handleSkim,
  };
}
