export interface PdbResidueNormalizationResult {
  content: string;
  converted: boolean;
  message: string | null;
  residueCountByChain: Record<string, number>;
}

const PDB_RESIDUE_FIELD_START = 22;
const PDB_RESIDUE_FIELD_END = 26;

function isProteinAtomRecord(line: string): boolean {
  return line.startsWith('ATOM') && line.length >= PDB_RESIDUE_FIELD_END;
}

function getChainId(line: string): string {
  return line.slice(21, 22).trim() || 'A';
}

function getResidueNumber(line: string): number | null {
  const value = Number.parseInt(line.slice(PDB_RESIDUE_FIELD_START, PDB_RESIDUE_FIELD_END).trim(), 10);
  return Number.isFinite(value) ? value : null;
}

function getResidueKey(line: string): string {
  const residueNumber = line.slice(PDB_RESIDUE_FIELD_START, PDB_RESIDUE_FIELD_END).trim();
  const insertionCode = line.slice(26, 27).trim();
  return `${residueNumber}:${insertionCode}`;
}

function formatResidueNumber(value: number): string {
  if (value < -999 || value > 9999) {
    throw new Error(`Cannot write residue number ${value}; PDB residue IDs must fit in columns 23-26.`);
  }
  return String(value).padStart(4, ' ');
}

function buildNormalizationMessage(residueCountByChain: Record<string, number>): string {
  const formatted = Object.entries(residueCountByChain)
    .map(([chain, count]) => `chain ${chain} (1-${count})`)
    .join(', ');
  return `Renumbered PDB protein residues to sequential 1-based convention for ${formatted}.`;
}

export function normalizePdbResiduesToOneIndexed(content: string): PdbResidueNormalizationResult {
  const lines = content.split(/\r?\n/);
  const residuesByChain = new Map<string, { order: string[]; originalNumbers: Map<string, number> }>();

  for (const line of lines) {
    if (!isProteinAtomRecord(line)) continue;

    const residueNumber = getResidueNumber(line);
    if (residueNumber == null) continue;

    const chainId = getChainId(line);
    const residueKey = getResidueKey(line);
    let chain = residuesByChain.get(chainId);
    if (!chain) {
      chain = { order: [], originalNumbers: new Map<string, number>() };
      residuesByChain.set(chainId, chain);
    }

    if (!chain.originalNumbers.has(residueKey)) {
      chain.order.push(residueKey);
      chain.originalNumbers.set(residueKey, residueNumber);
    }
  }

  const normalizedResidueByChain = new Map<string, Map<string, number>>();
  const residueCountByChain: Record<string, number> = {};
  let converted = false;

  for (const [chainId, chain] of residuesByChain.entries()) {
    residueCountByChain[chainId] = chain.order.length;
    const normalizedResidues = new Map<string, number>();

    chain.order.forEach((residueKey, index) => {
      const normalizedNumber = index + 1;
      const originalNumber = chain.originalNumbers.get(residueKey);
      normalizedResidues.set(residueKey, normalizedNumber);
      if (originalNumber !== normalizedNumber) {
        converted = true;
      }
    });

    normalizedResidueByChain.set(chainId, normalizedResidues);
  }

  if (!converted) {
    return {
      content,
      converted: false,
      message: null,
      residueCountByChain,
    };
  }

  const normalizedLines = lines.map((line) => {
    if (!isProteinAtomRecord(line)) return line;

    const chainId = getChainId(line);
    const residueKey = getResidueKey(line);
    const normalizedResidue = normalizedResidueByChain.get(chainId)?.get(residueKey);
    if (normalizedResidue == null) return line;

    const normalizedResidueField = formatResidueNumber(normalizedResidue);
    return `${line.slice(0, PDB_RESIDUE_FIELD_START)}${normalizedResidueField}${line.slice(PDB_RESIDUE_FIELD_END)}`;
  });

  return {
    content: normalizedLines.join('\n'),
    converted: true,
    message: buildNormalizationMessage(residueCountByChain),
    residueCountByChain,
  };
}
