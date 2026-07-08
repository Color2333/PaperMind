import type { ReactNode } from "react";

function ReportSection({
  icon,
  title,
  content,
}: {
  icon: ReactNode;
  title: string;
  content: string;
}) {
  return (
    <div>
      <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
        {icon}
        {title}
      </h4>
      <div className="bg-page dark:bg-page/50 rounded-xl px-4 py-3">
        <p className="text-ink-secondary text-sm leading-relaxed whitespace-pre-wrap">{content}</p>
      </div>
    </div>
  );
}

export default ReportSection;
