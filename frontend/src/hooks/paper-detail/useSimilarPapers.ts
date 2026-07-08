import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { paperApi } from "@/services/api";

type Toast = (type: ToastType, message: string) => void;

interface UseSimilarPapersParams {
  id: string | undefined;
  toast: Toast;
  setReportTab: Dispatch<SetStateAction<string>>;
}

export function useSimilarPapers({ id, toast, setReportTab }: UseSimilarPapersParams) {
  const [similarIds, setSimilarIds] = useState<string[]>([]);
  const [similarItems, setSimilarItems] = useState<
    { id: string; title: string; arxiv_id?: string; read_status?: string }[]
  >([]);
  const [similarLoading, setSimilarLoading] = useState(false);

  const handleSimilar = async () => {
    if (!id) return;
    setSimilarLoading(true);
    setReportTab("similar");
    try {
      const res = await paperApi.similar(id);
      setSimilarIds(res.similar_ids);
      if (res.items) setSimilarItems(res.items);
    } catch {
      toast("error", "获取相似论文失败");
    } finally {
      setSimilarLoading(false);
    }
  };

  return {
    similarIds,
    setSimilarIds,
    similarItems,
    setSimilarItems,
    similarLoading,
    setSimilarLoading,
    handleSimilar,
  };
}
