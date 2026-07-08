function ChainItem({ label, text }: { label: string; text: string }) {
  return (
    <div className="border-border bg-surface/50 rounded-xl border px-4 py-3">
      <p className="text-ink-tertiary mb-1 text-xs font-semibold">{label}</p>
      <p className="text-ink-secondary text-sm leading-relaxed whitespace-pre-wrap">{text}</p>
    </div>
  );
}

export default ChainItem;
