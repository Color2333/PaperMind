import { useState, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { pipelineApi } from "@/services/api";
import type { DeepDiveReport } from "@/types";

type Toast = (type: ToastType, message: string) => void;

interface UseDeepReadParams {
  id: string | undefined;
  toast: Toast;
  setReportTab: Dispatch<SetStateAction<string>>;
}

export function useDeepRead({ id, toast, setReportTab }: UseDeepReadParams) {
  const [deepReport, setDeepReport] = useState<DeepDiveReport | null>(null);
  const [savedDeep, setSavedDeep] = useState<{
    deep_dive_md: string;
    key_insights: Record<string, unknown>;
  } | null>(null);
  const [deepLoading, setDeepLoading] = useState(false);
  const deepAbort = useRef<AbortController | null>(null);

  const handleDeep = async () => {
    if (!id) return;
    setDeepLoading(true);
    setReportTab("deep");
    try {
      const report = await pipelineApi.deep(id);
      setDeepReport(report);
      toast("success", "精读完成");
    } catch {
      toast("error", "精读失败");
    } finally {
      setDeepLoading(false);
    }
  };

  return {
    deepReport,
    setDeepReport,
    savedDeep,
    setSavedDeep,
    deepLoading,
    setDeepLoading,
    deepAbort,
    handleDeep,
  };
}
