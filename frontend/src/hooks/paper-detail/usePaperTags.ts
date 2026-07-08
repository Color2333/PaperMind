import { useState, useCallback } from "react";
import type { Dispatch, SetStateAction } from "react";
import type { ToastType } from "@/contexts/ToastContext";
import { tagApi } from "@/services/api";
import type { Paper, Tag as TagType } from "@/types";

type Toast = (type: ToastType, message: string) => void;

interface UsePaperTagsParams {
  paperId: string | undefined;
  toast: Toast;
  paper: Paper | null;
  setPaper: Dispatch<SetStateAction<Paper | null>>;
}

export function usePaperTags({ paperId, toast, paper, setPaper }: UsePaperTagsParams) {
  const [allTags, setAllTags] = useState<TagType[]>([]);
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [newTagName, setNewTagName] = useState("");
  const [newTagColor, setNewTagColor] = useState("#3b82f6");
  const [tagsLoading, setTagsLoading] = useState(false);

  /* 加载标签列表 */
  const loadTags = useCallback(async () => {
    try {
      const res = await tagApi.list();
      setAllTags(res.items);
    } catch {
      // 静默失败
    }
  }, []);

  /* 标签管理 */
  const handleToggleTag = useCallback(
    async (tagId: string, isSelected: boolean) => {
      if (!paperId) return;
      try {
        if (isSelected) {
          await tagApi.removePaperTag(paperId, tagId);
          setPaper((prev) =>
            prev
              ? {
                  ...prev,
                  tags: (prev.tags || []).filter((t) => t.id !== tagId),
                }
              : prev
          );
        } else {
          const res = await tagApi.addPaperTag(paperId, tagId);
          setPaper((prev) =>
            prev
              ? {
                  ...prev,
                  tags: [...(prev.tags || []), res.tag],
                }
              : prev
          );
        }
      } catch {
        toast("error", "标签操作失败");
      }
    },
    [paperId, toast]
  );

  const handleCreateTag = useCallback(async () => {
    if (!newTagName.trim()) {
      toast("error", "标签名称不能为空");
      return;
    }
    setTagsLoading(true);
    try {
      const newTag = await tagApi.create(newTagName.trim(), newTagColor);
      setAllTags((prev) => [...prev, newTag]);
      if (paperId) {
        const res = await tagApi.addPaperTag(paperId, newTag.id);
        setPaper((prev) =>
          prev
            ? {
                ...prev,
                tags: [...(prev.tags || []), res.tag],
              }
            : prev
        );
      }
      toast("success", "标签创建成功");
      setTagModalOpen(false);
      setNewTagName("");
      setNewTagColor("#3b82f6");
    } catch {
      toast("error", "创建标签失败");
    } finally {
      setTagsLoading(false);
    }
  }, [newTagName, newTagColor, paperId, toast]);

  return {
    allTags,
    setAllTags,
    tagModalOpen,
    setTagModalOpen,
    newTagName,
    setNewTagName,
    newTagColor,
    setNewTagColor,
    tagsLoading,
    setTagsLoading,
    loadTags,
    handleToggleTag,
    handleCreateTag,
  };
}
