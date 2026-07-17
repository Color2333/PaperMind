import { useState, useEffect, useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { paperApi, tagApi } from "@/services/api";
import type {
  Paper,
  FigureAnalysisItem,
  ReasoningChainResult,
  Tag as TagType,
} from "@/types";

type Toast = (type: ToastType, message: string) => void;

interface UsePaperCoreParams {
  id: string | undefined;
  toast: Toast;
  paper: Paper | null;
  setPaper: Dispatch<SetStateAction<Paper | null>>;
  setFigures: Dispatch<SetStateAction<FigureAnalysisItem[]>>;
  setAllTags: Dispatch<SetStateAction<TagType[]>>;
  setReasoning: Dispatch<SetStateAction<ReasoningChainResult | null>>;
  setSavedSkim: Dispatch<
    SetStateAction<{
      summary_md: string;
      skim_score: number | null;
      key_insights: Record<string, unknown>;
    } | null>
  >;
  setSavedDeep: Dispatch<
    SetStateAction<{
      deep_dive_md: string;
      key_insights: Record<string, unknown>;
    } | null>
  >;
  setReportTab: Dispatch<SetStateAction<string>>;
}

export function usePaperCore({
  id,
  toast,
  paper,
  setPaper,
  setFigures,
  setAllTags,
  setReasoning,
  setSavedSkim,
  setSavedDeep,
  setReportTab,
}: UsePaperCoreParams) {
  const [loading, setLoading] = useState(true);
  const [embedDone, setEmbedDone] = useState<boolean | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      paperApi.detail(id),
      paperApi.getFigures(id).catch(() => ({ items: [] as FigureAnalysisItem[] })),
      tagApi.list().catch(() => ({ items: [] as TagType[] })),
    ])
      .then(([p, figRes, tagRes]) => {
        setPaper(p);
        setEmbedDone(p.has_embedding ?? false);
        if (p.skim_report) setSavedSkim(p.skim_report);
        if (p.deep_report) setSavedDeep(p.deep_report);
        setFigures(figRes.items);
        setAllTags(tagRes.items);
        const rc = p.metadata?.reasoning_chain as ReasoningChainResult | undefined;
        if (rc) setReasoning(rc);
        if (p.deep_report) setReportTab("deep");
        else if (p.skim_report) setReportTab("skim");
      })
      .catch(() => {
        toast("error", "加载论文详情失败");
      })
      .finally(() => setLoading(false));
  }, [id, toast]);

  const handleToggleFavorite = useCallback(async () => {
    if (!id || !paper) return;
    const prevFavorited = paper.favorited;
    try {
      const res = await paperApi.toggleFavorite(id);
      setPaper((prev) => (prev ? { ...prev, favorited: res.favorited } : prev));
    } catch {
      toast("error", "收藏操作失败");
      setPaper((prev) => (prev ? { ...prev, favorited: prevFavorited } : prev));
    }
  }, [id, paper, toast]);

  const handleToggleRejected = useCallback(async () => {
    if (!id || !paper) return;
    const prevRejected = paper.rejected;
    try {
      const res = await paperApi.toggleRejected(id);
      setPaper((prev) => (prev ? { ...prev, rejected: res.rejected } : prev));
      toast(res.rejected ? "info" : "info", res.rejected ? "已标记为不感兴趣" : "已取消标记");
    } catch {
      toast("error", "操作失败");
      setPaper((prev) => (prev ? { ...prev, rejected: prevRejected } : prev));
    }
  }, [id, paper, toast]);

  return {
    loading,
    embedDone,
    setEmbedDone,
    handleToggleFavorite,
    handleToggleRejected,
  };
}
