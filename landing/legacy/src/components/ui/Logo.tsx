// Real Solace logo (the actual brand asset, not a recreation).
// On dark sections it's tinted white; on light sections it shows natural.
type Props = { className?: string; light?: boolean; compact?: boolean };

export default function Logo({ className = '', light = false, compact = false }: Props) {
  return (
    <img
      src="/assets/solace-logo.png"
      alt="Solace"
      className={`w-auto select-none ${compact ? 'h-7' : 'h-8'} ${
        light ? '[filter:brightness(0)_invert(1)]' : ''
      } ${className}`}
      draggable={false}
    />
  );
}
