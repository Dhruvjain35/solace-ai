type Props = {
  label: string;
  selected: boolean;
  onToggle: () => void;
};

export function Chip({ label, selected, onToggle }: Props) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`min-h-[44px] px-4 rounded-full text-sm font-medium transition-all active:scale-[0.97] ${
        selected
          ? "bg-primary text-white shadow-soft"
          : "bg-surface-lowest text-ink ring-1 ring-line hover:ring-primary/40"
      }`}
    >
      {label}
    </button>
  );
}
