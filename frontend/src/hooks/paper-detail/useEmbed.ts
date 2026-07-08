import { useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { pipelineApi } from "@/services/api";

type Toast = (type: ToastType, message: string) => void;

interface UseEmbedParams {
  id: string | undefined;
  toast: Toast;
  embedDone: boolean | null;
  setEmbedDone: Dispatch<SetStateAction<boolean | null>>;
}

export function useEmbed({ id, toast, setEmbedDone }: UseEmbedParams) {
  const [embedLoading, setEmbedLoading] = useState(false);

  const handleEmbed = async () => {
    if (!id) return;
    setEmbedLoading(true);
    try {
      await pipelineApi.embed(id);
      setEmbedDone(true);
      toast("success", "嵌入完成");
    } catch {
      toast("error", "嵌入失败");
    } finally {
      setEmbedLoading(false);
    }
  };

  return { embedLoading, setEmbedLoading, handleEmbed };
}
