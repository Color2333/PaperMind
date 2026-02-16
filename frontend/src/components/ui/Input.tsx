/**
 * 输入框组件
 * @author Bamzc
 */
import { cn } from "@/lib/utils";
import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className, ...props }, ref) => (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-sm font-medium text-ink">{label}</label>
      )}
      <input
        ref={ref}
        className={cn(
          "h-10 w-full rounded-lg border bg-surface px-3.5 text-sm text-ink transition-colors",
          "placeholder:text-ink-placeholder",
          "focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20",
          error ? "border-error" : "border-border",
          className
        )}
        {...props}
      />
      {error && <p className="text-xs text-error">{error}</p>}
    </div>
  )
);
Input.displayName = "Input";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, className, ...props }, ref) => (
    <div className="space-y-1.5">
      {label && (
        <label className="block text-sm font-medium text-ink">{label}</label>
      )}
      <textarea
        ref={ref}
        className={cn(
          "min-h-[80px] w-full resize-y rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm text-ink transition-colors",
          "placeholder:text-ink-placeholder",
          "focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20",
          className
        )}
        {...props}
      />
    </div>
  )
);
Textarea.displayName = "Textarea";
