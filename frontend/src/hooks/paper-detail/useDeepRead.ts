import { useState, useRef, useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { pipelineApi } from "@/services/api";
import type { DeepDiveReport } from "@/types";
import { pollTaskUntilDone } from "./pollTask";

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
  const cancelledRef = useRef(false);

  const handleDeep = useCallback(async () => {
    if (!id) return;
    setDeepLoading(true);
    setReportTab("deep");
    cancelledRef.current = false;
    try {
      const { task_id } = await pipelineApi.deep(id);
      const report = await pollTaskUntilDone<DeepDiveReport>(task_id, () => cancelledRef.current);
      setDeepReport(report);
      toast("success", "精读完成");
    } catch (e) {
      if (!cancelledRef.current) {
        toast("error", e instanceof Error ? e.message : "精读失败");
      }
    } finally {
      setDeepLoading(false);
    }
  }, [id, setReportTab, toast]);

  const cancelDeep = useCallback(() => {
    cancelledRef.current = true;
    setDeepLoading(false);
  }, []);

  return {
    deepReport,
    setDeepReport,
    savedDeep,
    setSavedDeep,
    deepLoading,
    setDeepLoading,
    deepAbort,
    cancelDeep,
    handleDeep,
  };
}
