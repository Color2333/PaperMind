/**
 * 后台任务轮询 helper — 配合 PR5 后台化的 skim/deep/embed 端点
 * 端点现在返回 {task_id, status}，前端轮询 tasksApi.getStatus 直到 finished，再 getResult 取结果
 * @author Color2333
 */
import { tasksApi } from "@/services/api";
import type { TaskStatus } from "@/types";

const POLL_INTERVAL_MS = 2000;
const MAX_WAIT_MS = 5 * 60 * 1000; // 5 分钟超时
const MAX_ERRORS = 10; // 连续查询失败上限

/**
 * 轮询任务直到完成/失败/超时。
 * @returns 完成时返回 getResult 的结果；失败/超时抛错。
 */
export async function pollTaskUntilDone<T>(
  taskId: string,
  isCancelled: () => boolean,
): Promise<T> {
  const start = Date.now();
  let consecutiveErrors = 0;

  // 递归 setTimeout 轮询（避免 setInterval 难以取消 + 退避）
  const poll = async (): Promise<T> => {
    if (isCancelled()) throw new Error("已取消");
    if (Date.now() - start > MAX_WAIT_MS) {
      throw new Error("任务超时，请稍后在详情页查看结果");
    }
    let status: TaskStatus;
    try {
      status = await tasksApi.getStatus(taskId);
      consecutiveErrors = 0;
    } catch {
      consecutiveErrors += 1;
      if (consecutiveErrors >= MAX_ERRORS) {
        throw new Error("任务状态查询持续失败");
      }
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      return poll();
    }
    if (!status.finished) {
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      return poll();
    }
    if (!status.success) {
      throw new Error(status.error || "任务失败");
    }
    // 完成：取结果
    return (await tasksApi.getResult(taskId)) as T;
  };

  return poll();
}
