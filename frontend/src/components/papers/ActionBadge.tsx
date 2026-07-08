import { Bot, CalendarClock, Download, FileText, Tag } from "lucide-react";

function ActionBadge({ type }: { type: string }) {
  const cls = "h-3 w-3 shrink-0";
  switch (type) {
    case "agent_collect":
      return <Bot className={`${cls} text-info`} />;
    case "auto_collect":
      return <CalendarClock className={`${cls} text-success`} />;
    case "manual_collect":
      return <Download className={`${cls} text-primary`} />;
    case "subscription_ingest":
      return <Tag className={`${cls} text-warning`} />;
    default:
      return <FileText className={`${cls} text-ink-tertiary`} />;
  }
}

export default ActionBadge;
