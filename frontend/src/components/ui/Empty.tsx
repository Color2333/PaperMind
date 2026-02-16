/**
 * 空状态组件
 * @author Bamzc
 */
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

interface EmptyProps {
  icon?: ReactNode;
  title?: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function Empty({
  icon,
  title = "暂无数据",
  description,
  action,
  className,
}: EmptyProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-16 text-center", className)}>
      <div className="mb-4 text-ink-tertiary">
        {icon || <Inbox className="h-12 w-12" />}
      </div>
      <h3 className="text-sm font-medium text-ink-secondary">{title}</h3>
      {description && (
        <p className="mt-1 max-w-sm text-sm text-ink-tertiary">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
