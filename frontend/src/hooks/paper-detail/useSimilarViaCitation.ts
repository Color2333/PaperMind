import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import type { SimilarityItem } from "@/types";
import { graphApi } from "@/services/api";

type Toast = (type: ToastType, message: string) => void;

interface UseSimilarViaCitationParams {
  id: string | undefined;
  toast: Toast;
  setReportTab: Dispatch<SetStateAction<string>>;
}

export function useSimilarViaCitation({ id, toast, setReportTab }: UseSimilarViaCitationParams) {
  const [citationSimilarItems, setCitationSimilarItems] = useState<SimilarityItem[]>([]);
  const [citationSimilarLoading, setCitationSimilarLoading] = useState(false);

  const handleCitationSimilar = async () => {
    if (!id) return;
    setCitationSimilarLoading(true);
    setReportTab("citation-similar");
    try {
      const res = await graphApi.similarViaCitation(id);
      setCitationSimilarItems(res.items);
      if (res.note) {
        toast("info", res.note);
      } else if (res.items.length === 0) {
        toast("info", "未找到引用图补强候选");
      }
    } catch {
      toast("error", "引用图补强查询失败");
    } finally {
      setCitationSimilarLoading(false);
    }
  };

  return {
    citationSimilarItems,
    setCitationSimilarItems,
    citationSimilarLoading,
    setCitationSimilarLoading,
    handleCitationSimilar,
  };
}
