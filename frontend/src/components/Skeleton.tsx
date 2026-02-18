/**
 * 骨架屏组件
 * @author Bamzc
 */
import { cn } from "@/lib/utils";

function SkeletonBlock({ className }: { className?: string }) {
  return <div className={cn("animate-shimmer rounded-lg bg-border/60", className)} />;
}

/**
 * 论文列表骨架 - 模拟论文卡片
 */
export function PaperListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-xl border border-border bg-surface p-4">
          <div className="flex items-start gap-3">
            <SkeletonBlock className="h-5 w-5 shrink-0 rounded-md" />
            <div className="min-w-0 flex-1 space-y-2">
              <SkeletonBlock className="h-4 w-3/4" />
              <SkeletonBlock className="h-3 w-1/2" />
              <div className="flex gap-2 pt-1">
                <SkeletonBlock className="h-5 w-16 rounded-full" />
                <SkeletonBlock className="h-5 w-20 rounded-full" />
                <SkeletonBlock className="h-5 w-14 rounded-full" />
              </div>
            </div>
            <SkeletonBlock className="h-4 w-16 shrink-0" />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * 统计卡片骨架 - Dashboard 使用
 */
export function StatCardSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-xl border border-border bg-surface p-4 space-y-3">
          <SkeletonBlock className="h-3 w-20" />
          <SkeletonBlock className="h-7 w-16" />
          <SkeletonBlock className="h-2 w-24" />
        </div>
      ))}
    </div>
  );
}

/**
 * 论文详情骨架
 */
export function PaperDetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <SkeletonBlock className="h-8 w-8 rounded-lg" />
        <SkeletonBlock className="h-6 w-48" />
      </div>
      <div className="space-y-3">
        <SkeletonBlock className="h-5 w-full" />
        <SkeletonBlock className="h-5 w-5/6" />
        <SkeletonBlock className="h-4 w-2/3" />
      </div>
      <div className="flex gap-2">
        <SkeletonBlock className="h-9 w-24 rounded-lg" />
        <SkeletonBlock className="h-9 w-24 rounded-lg" />
        <SkeletonBlock className="h-9 w-24 rounded-lg" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2 rounded-xl border border-border p-4">
          <SkeletonBlock className="h-4 w-20" />
          <SkeletonBlock className="h-20 w-full" />
        </div>
        <div className="space-y-2 rounded-xl border border-border p-4">
          <SkeletonBlock className="h-4 w-20" />
          <SkeletonBlock className="h-20 w-full" />
        </div>
      </div>
    </div>
  );
}

export default SkeletonBlock;
