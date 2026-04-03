/**
 * Renders full SMILES with wrapping — no ellipsis truncation so wide layouts
 * can use all available horizontal space.
 */
interface SmilesCellProps {
  smiles: string;
}

export default function SmilesCell({ smiles }: SmilesCellProps) {
  return (
    <span className="block max-w-none whitespace-normal break-all font-data text-[11px] leading-snug text-foreground/90">
      {smiles}
    </span>
  );
}
