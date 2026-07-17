import { useState, useRef, useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { paperApi, pipelineApi } from "@/services/api";
import type { Paper, SkimReport } from "@/types";
import { pollTaskUntilDone } from "./pollTask";

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
  const cancelledRef = useRef(false);

  const handleSkim = useCallback(async () => {
    if (!id) return;
    setSkimLoading(true);
    setReportTab("skim");
    cancelledRef.current = false;
    try {
      // 后台任务化：端点返回 task_id，轮询直到完成再 getResult 取结果
      const { task_id } = await pipelineApi.skim(id);
      const report = await pollTaskUntilDone<SkimReport>(task_id, () => cancelledRef.current);
      setSkimReport(report);
      // 刷新论文信息，更新粗读报告
      const updated = await paperApi.detail(id);
      setPaper(updated);
      if (updated.skim_report) setSavedSkim(updated.skim_report);
      toast("success", "粗读完成");
    } catch (e) {
      if (!cancelledRef.current) {
        toast("error", e instanceof Error ? e.message : "粗读失败");
      }
    } finally {
      setSkimLoading(false);
    }
  }, [id, setReportTab, toast, setPaper]);

  // onCancel：标记取消，pollTaskUntilDone 下次检查时抛错退出
  const cancelSkim = useCallback(() => {
    cancelledRef.current = true;
    setSkimLoading(false);
  }, []);

  return {
    skimReport,
    setSkimReport,
    savedSkim,
    setSavedSkim,
    skimLoading,
    setSkimLoading,
    skimAbort,
    cancelSkim,
    handleSkim,
  };
}
