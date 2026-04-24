interface DeltaCardProps {
  label: string;
  content: string;
  variant: 'before' | 'after' | 'delta';
}

export function DeltaCard({ label, content, variant }: DeltaCardProps) {
  const colors = {
    before: 'border-white/20 bg-white/5',
    after: 'border-primary/30 bg-primary/5',
    delta: 'border-amber-500/30 bg-amber-500/5',
  };

  const labelColors = {
    before: 'text-white/40',
    after: 'text-primary',
    delta: 'text-amber-400',
  };

  return (
    <div className={`rounded-xl border p-4 ${colors[variant]}`}>
      <p className={`mb-2 text-xs font-medium ${labelColors[variant]}`}>{label}</p>
      <p className="text-sm leading-relaxed text-white/80">{content || '...'}</p>
    </div>
  );
}
