import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { paperApi } from "@/services/api";
import type { FigureAnalysisItem } from "@/types";

type Toast = (type: ToastType, message: string) => void;

interface UseFiguresParams {
  id: string | undefined;
  toast: Toast;
  setReportTab: Dispatch<SetStateAction<string>>;
}

export function useFigures({ id, toast, setReportTab }: UseFiguresParams) {
  const [figures, setFigures] = useState<FigureAnalysisItem[]>([]);
  const [figuresAnalyzing, setFiguresAnalyzing] = useState(false);

  const handleAnalyzeFigures = async () => {
    if (!id) return;
    setFiguresAnalyzing(true);
    setReportTab("figures");
    try {
      const res = await paperApi.analyzeFigures(id, 10);
      setFigures(res.items);
      toast("success", `解读完成，共 ${res.items.length} 张图表`);
    } catch {
      toast("error", "图表分析失败");
    } finally {
      setFiguresAnalyzing(false);
    }
  };

  return {
    figures,
    setFigures,
    figuresAnalyzing,
    setFiguresAnalyzing,
    handleAnalyzeFigures,
  };
}
