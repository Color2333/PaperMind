import { memo, useState, useCallback, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";
import type { ChatItem } from "@/contexts/AgentSessionContext";

interface ChatNavBarProps {
  items: ChatItem[];
  scrollAreaRef: React.RefObject<HTMLDivElement | null>;
}

interface UserMessageMarker {
  id: string;
  content: string;
  top: number;
  height: number;
}

const ChatNavBar = memo(function ChatNavBar({ items, scrollAreaRef }: ChatNavBarProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [markers, setMarkers] = useState<UserMessageMarker[]>([]);
  const rafRef = useRef<number | null>(null);

  const updateMarkers = useCallback(() => {
    const scrollEl = scrollAreaRef.current;
    if (!scrollEl) return;

    const userMessages = items.filter((item) => item.type === "user");
    if (userMessages.length === 0) {
      setMarkers([]);
      return;
    }

    const scrollRect = scrollEl.getBoundingClientRect();

    const newMarkers: UserMessageMarker[] = [];
    for (const item of userMessages) {
      const msgEl = scrollEl.querySelector(`[data-message-id="${item.id}"]`);
      if (msgEl) {
        const rect = msgEl.getBoundingClientRect();
        newMarkers.push({
          id: item.id,
          content: item.content.slice(0, 300) + (item.content.length > 300 ? "..." : ""),
          top: rect.top - scrollRect.top,
          height: rect.height,
        });
      }
    }
    setMarkers(newMarkers);
  }, [items, scrollAreaRef]);

  useEffect(() => {
    const scrollEl = scrollAreaRef.current;
    if (!scrollEl) return;

    const handleScroll = () => {
      if (rafRef.current) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        updateMarkers();
      });
    };

    updateMarkers();
    scrollEl.addEventListener("scroll", handleScroll, { passive: true });
    return () => scrollEl.removeEventListener("scroll", handleScroll);
  }, [items, scrollAreaRef, updateMarkers]);

  const jumpToMessage = useCallback(
    (msgId: string) => {
      const scrollEl = scrollAreaRef.current;
      if (!scrollEl) return;
      const msgEl = scrollEl.querySelector(`[data-message-id="${msgId}"]`);
      if (msgEl) {
        msgEl.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    },
    [scrollAreaRef]
  );

  if (markers.length === 0) return null;

  return (
    <div
      className="pointer-events-none fixed top-[120px] right-4 z-20 flex w-6 flex-col items-center"
      style={{ height: "calc(100vh - 200px)" }}
      onMouseLeave={() => setHoveredId(null)}
    >
      <div className="pointer-events-auto relative w-full flex-1">
        <div className="bg-border/30 absolute top-0 left-1/2 h-full w-0.5 -translate-x-1/2 rounded-full" />
        {markers.map((marker) => {
          return (
            <div
              key={marker.id}
              className="group absolute left-1/2 -translate-x-1/2"
              style={{ top: `${marker.top}px` }}
            >
              <button
                type="button"
                onClick={() => jumpToMessage(marker.id)}
                onMouseEnter={() => setHoveredId(marker.id)}
                onMouseLeave={() => setHoveredId(null)}
                className={cn(
                  "border-primary h-2.5 w-2.5 rounded-full border-2 bg-white transition-all duration-200",
                  "hover:h-3.5 hover:w-3.5 hover:shadow-md",
                  "focus:ring-primary/50 focus:ring-2 focus:outline-none"
                )}
              />

              {hoveredId === marker.id && (
                <div
                  className={cn(
                    "absolute top-1/2 right-7 -translate-y-1/2",
                    "bg-surface border-border rounded-lg border shadow-lg",
                    "text-ink w-72 px-3 py-2 text-xs",
                    "animate-in fade-in slide-in-from-right-2 duration-200"
                  )}
                >
                  <span className="bg-primary/10 text-primary rounded px-1.5 py-0.5 text-[10px] font-medium">
                    用户
                  </span>
                  <p className="text-ink-secondary mt-1 max-h-32 overflow-y-auto leading-relaxed break-words whitespace-pre-wrap">
                    {marker.content}
                  </p>
                  <div className="absolute top-1/2 right-0 translate-x-2 -translate-y-1/2">
                    <div className="border-l-surface border-4 border-transparent" />
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
});

export { ChatNavBar };
