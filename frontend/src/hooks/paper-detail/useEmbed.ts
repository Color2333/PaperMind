import { useState, useRef, useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { pipelineApi } from "@/services/api";
import { pollTaskUntilDone } from "./pollTask";

type Toast = (type: ToastType, message: string) => void;

interface UseEmbedParams {
  id: string | undefined;
  toast: Toast;
  embedDone: boolean | null;
  setEmbedDone: Dispatch<SetStateAction<boolean | null>>;
}

export function useEmbed({ id, toast, setEmbedDone }: UseEmbedParams) {
  const [embedLoading, setEmbedLoading] = useState(false);
  const cancelledRef = useRef(false);

  const handleEmbed = useCallback(async () => {
    if (!id) return;
    setEmbedLoading(true);
    cancelledRef.current = false;
    try {
      const { task_id } = await pipelineApi.embed(id);
      await pollTaskUntilDone<{ status: string; paper_id: string }>(
        task_id,
        () => cancelledRef.current,
      );
      setEmbedDone(true);
      toast("success", "嵌入完成");
    } catch (e) {
      if (!cancelledRef.current) {
        toast("error", e instanceof Error ? e.message : "嵌入失败");
      }
    } finally {
      setEmbedLoading(false);
    }
  }, [id, toast, setEmbedDone]);

  const cancelEmbed = useCallback(() => {
    cancelledRef.current = true;
    setEmbedLoading(false);
  }, []);

  return { embedLoading, setEmbedLoading, handleEmbed, cancelEmbed };
}
