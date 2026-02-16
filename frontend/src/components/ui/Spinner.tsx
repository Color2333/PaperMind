/**
 * 加载指示器
 * @author Bamzc
 */
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

interface SpinnerProps {
  className?: string;
  text?: string;
}

export function Spinner({ className, text = "加载中..." }: SpinnerProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-16", className)}>
      <Loader2 className="h-8 w-8 animate-spin text-primary" />
      <p className="mt-3 text-sm text-ink-secondary">{text}</p>
    </div>
  );
}
