import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import type { SimilarityItem } from "@/types";
import { paperApi } from "@/services/api";

type Toast = (type: ToastType, message: string) => void;

interface UseDuplicatesParams {
  id: string | undefined;
  toast: Toast;
  setReportTab: Dispatch<SetStateAction<string>>;
}

export function useDuplicates({ id, toast, setReportTab }: UseDuplicatesParams) {
  const [duplicateItems, setDuplicateItems] = useState<SimilarityItem[]>([]);
  const [duplicateLoading, setDuplicateLoading] = useState(false);

  const handleDuplicates = async () => {
    if (!id) return;
    setDuplicateLoading(true);
    setReportTab("duplicates");
    try {
      const res = await paperApi.duplicates(id);
      setDuplicateItems(res.duplicates);
      if (res.count === 0) {
        toast("info", "未检测到疑似重复论文");
      }
    } catch {
      toast("error", "查重失败");
    } finally {
      setDuplicateLoading(false);
    }
  };

  return {
    duplicateItems,
    setDuplicateItems,
    duplicateLoading,
    setDuplicateLoading,
    handleDuplicates,
  };
}
