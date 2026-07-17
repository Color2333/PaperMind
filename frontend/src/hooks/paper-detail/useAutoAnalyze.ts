import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { paperApi, pipelineApi } from "@/services/api";
import type {
  Paper,
  FigureAnalysisItem,
  ReasoningChainResult,
  DeepDiveReport,
  SkimReport,
} from "@/types";
import { pollTaskUntilDone } from "./pollTask";

type Toast = (type: ToastType, message: string) => void;

interface UseAutoAnalyzeParams {
  id: string | undefined;
  toast: Toast;
  paper: Paper | null;
  hasSkim: boolean;
  hasDeep: boolean;
  figures: FigureAnalysisItem[];
  reasoning: ReasoningChainResult | null;
  setReportTab: Dispatch<SetStateAction<string>>;
  setEmbedLoading: Dispatch<SetStateAction<boolean>>;
  setEmbedDone: Dispatch<SetStateAction<boolean | null>>;
  setSkimLoading: Dispatch<SetStateAction<boolean>>;
  setSkimReport: Dispatch<SetStateAction<SkimReport | null>>;
  setDeepLoading: Dispatch<SetStateAction<boolean>>;
  setDeepReport: Dispatch<SetStateAction<DeepDiveReport | null>>;
  setFiguresAnalyzing: Dispatch<SetStateAction<boolean>>;
  setFigures: Dispatch<SetStateAction<FigureAnalysisItem[]>>;
  setReasoningLoading: Dispatch<SetStateAction<boolean>>;
  setReasoning: Dispatch<SetStateAction<ReasoningChainResult | null>>;
}

export function useAutoAnalyze({
  id,
  toast,
  paper,
  hasSkim,
  hasDeep,
  figures,
  reasoning,
  setReportTab,
  setEmbedLoading,
  setEmbedDone,
  setSkimLoading,
  setSkimReport,
  setDeepLoading,
  setDeepReport,
  setFiguresAnalyzing,
  setFigures,
  setReasoningLoading,
  setReasoning,
}: UseAutoAnalyzeParams) {
  const [autoAnalyzing, setAutoAnalyzing] = useState(false);
  const [autoStage, setAutoStage] = useState("");

  const handleAutoAnalyze = async () => {
    if (!id || !paper) return;
    setAutoAnalyzing(true);
    try {
      // Step 1: 向量嵌入（不需要 PDF）
      if (!paper.has_embedding) {
        setAutoStage("向量嵌入中...");
        setEmbedLoading(true);
        try {
          const { task_id } = await pipelineApi.embed(id);
          await pollTaskUntilDone<{ status: string; paper_id: string }>(task_id, () => false);
          setEmbedDone(true);
        } catch {}
        setEmbedLoading(false);
      }

      // Step 2: 粗读（不需要 PDF）
      if (!hasSkim) {
        setAutoStage("粗读分析中...");
        setSkimLoading(true);
        setReportTab("skim");
        try {
          const { task_id } = await pipelineApi.skim(id);
          const r = await pollTaskUntilDone<SkimReport>(task_id, () => false);
          setSkimReport(r);
        } catch {}
        setSkimLoading(false);
      }

      if (paper.pdf_path) {
        // Step 3: 精读（需要 PDF）
        if (!hasDeep) {
          setAutoStage("精读分析中...");
          setDeepLoading(true);
          setReportTab("deep");
          try {
            const { task_id } = await pipelineApi.deep(id);
            const r = await pollTaskUntilDone<DeepDiveReport>(task_id, () => false);
            setDeepReport(r);
          } catch {}
          setDeepLoading(false);
        }

        // Step 4: 图表解读（需要 PDF）
        if (figures.length === 0) {
          setAutoStage("图表解读中...");
          setFiguresAnalyzing(true);
          setReportTab("figures");
          try {
            const r = await paperApi.analyzeFigures(id, 10);
            setFigures(r.items);
          } catch {}
          setFiguresAnalyzing(false);
        }

        // Step 5: 推理链（需要 PDF）
        if (!reasoning) {
          setAutoStage("推理链分析中...");
          setReasoningLoading(true);
          setReportTab("reasoning");
          try {
            const r = await paperApi.reasoningAnalysis(id);
            setReasoning(r.reasoning);
          } catch {}
          setReasoningLoading(false);
        }
      }

      setAutoStage("");
      toast("success", "深度分析完成");
      setReportTab("skim");
    } finally {
      setAutoAnalyzing(false);
      setAutoStage("");
    }
  };

  return { autoAnalyzing, autoStage, handleAutoAnalyze };
}
