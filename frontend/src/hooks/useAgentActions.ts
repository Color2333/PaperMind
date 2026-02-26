/**
 * Agent 工具操作管理 Hook
 * @author Color2333
 */
import { useState, useCallback } from "react";
import { agentApi } from "@/services/api";

export interface ActionState {
  pendingActions: Set<string>;
  confirmingActions: Set<string>;
}

export function useAgentActions(
  onStreamStart: (reader: ReadableStreamDefaultReader<Uint8Array>, signal?: AbortSignal) => void,
  onError: (error: Error) => void,
  setLoading: (loading: boolean) => void,
  cancelStream: () => void,
) {
  const [pendingActions, setPendingActions] = useState<Set<string>>(new Set());
  const [confirmingActions, setConfirmingActions] = useState<Set<string>>(new Set());

  /**
   * 添加待确认操作
   */
  const addPendingAction = useCallback((actionId: string) => {
    setPendingActions((prev) => new Set(prev).add(actionId));
  }, []);

  /**
   * 移除待确认操作
   */
  const removePendingAction = useCallback((actionId: string) => {
    setPendingActions((prev) => {
      const next = new Set(prev);
      next.delete(actionId);
      return next;
    });
  }, []);

  /**
   * 确认操作
   */
  const handleConfirm = useCallback(
    async (actionId: string) => {
      setConfirmingActions((prev) => new Set(prev).add(actionId));
      removePendingAction(actionId);
      cancelStream();
      setLoading(true);

      try {
        const ac = new AbortController();
        const resp = await agentApi.confirm(actionId);
        if (resp.body) {
          onStreamStart(resp.body.getReader(), ac.signal);
        } else {
          setLoading(false);
        }
      } catch (err) {
        onError(err instanceof Error ? err : new Error("确认失败"));
        setLoading(false);
      } finally {
        setConfirmingActions((prev) => {
          const next = new Set(prev);
          next.delete(actionId);
          return next;
        });
      }
    },
    [cancelStream, onStreamStart, onError, setLoading, removePendingAction],
  );

  /**
   * 拒绝操作
   */
  const handleReject = useCallback(
    async (actionId: string) => {
      removePendingAction(actionId);
      cancelStream();
      setLoading(true);

      try {
        const ac = new AbortController();
        const resp = await agentApi.reject(actionId);
        if (resp.body) {
          onStreamStart(resp.body.getReader(), ac.signal);
        } else {
          setLoading(false);
        }
      } catch (err) {
        onError(err instanceof Error ? err : new Error("拒绝操作失败"));
        setLoading(false);
      }
    },
    [cancelStream, onStreamStart, onError, setLoading, removePendingAction],
  );

  return {
    pendingActions,
    confirmingActions,
    addPendingAction,
    removePendingAction,
    handleConfirm,
    handleReject,
    hasPendingConfirm: pendingActions.size > 0,
  };
}
