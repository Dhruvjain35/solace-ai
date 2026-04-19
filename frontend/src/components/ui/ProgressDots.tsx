type Props = {
  total: number;
  current: number; // 1-based
};

export function ProgressDots({ total, current }: Props) {
  return (
    <div className="flex items-center gap-1.5" aria-label={`Step ${current} of ${total}`}>
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className={`h-1 rounded-full transition-all ${
            i < current ? "bg-primary w-8" : "bg-surface-high w-4"
          }`}
        />
      ))}
    </div>
  );
}
