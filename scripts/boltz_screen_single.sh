#!/usr/bin/env bash

set -euo pipefail

# Single ligand screening script to run Boltz-2 for a custom SMILES string
# Usage: boltz_screen_single.sh --smiles "SMILES_STRING" [--id LIGAND_ID] [--pdb PDB_FILE] [--msa MSA_FILE] [--out-dir OUT_DIR] [--hotspots RESIDUES]

# Default values (can be overridden via CLI flags or environment variables)
: "${PDB:=/home/conrad_hku/Drug_pipeline/input/NS5_crop_renum.pdb}"
: "${MSA:=/home/conrad_hku/Drug_pipeline/msa/NS5_crop.a3m}"
: "${OUT_DIR:=/media/data/conrad_hku/boltz_frag_valid}"
: "${HOTSPOTS:=16,67,138,153,184,185}"

SMILES=""
LIG_ID=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --smiles|-s)
      SMILES="$2"
      shift 2
      ;;
    --id|-i)
      LIG_ID="$2"
      shift 2
      ;;
    --pdb|-p)
      PDB="$2"
      shift 2
      ;;
    --msa|-m)
      MSA="$2"
      shift 2
      ;;
    --out-dir|-o)
      OUT_DIR="$2"
      shift 2
      ;;
    --hotspots|-h)
      HOTSPOTS="$2"
      shift 2
      ;;
    --help)
      echo "Usage: $0 --smiles SMILES_STRING [OPTIONS]"
      echo ""
      echo "Required:"
      echo "  --smiles, -s SMILES_STRING    SMILES string to screen"
      echo ""
      echo "Optional:"
      echo "  --id, -i LIGAND_ID            Ligand ID (default: auto-generated from SMILES hash)"
      echo "  --pdb, -p PDB_FILE            PDB file path (default: \$PDB or $PDB)"
      echo "  --msa, -m MSA_FILE            MSA file path (default: \$MSA or $MSA)"
      echo "  --out-dir, -o OUT_DIR         Output directory (default: \$OUT_DIR or $OUT_DIR)"
      echo "  --hotspots, -h RESIDUES       Comma-separated hotspot residues (default: \$HOTSPOTS or $HOTSPOTS)"
      echo "  --help                        Show this help message"
      exit 0
      ;;
    *)
      echo "ERROR: Unknown option: $1" >&2
      echo "Use --help for usage information" >&2
      exit 1
      ;;
  esac
done

# Validate required SMILES argument
if [ -z "$SMILES" ]; then
  echo "ERROR: --smiles is required" >&2
  echo "Use --help for usage information" >&2
  exit 1
fi

# Generate ligand ID from SMILES hash if not provided
if [ -z "$LIG_ID" ]; then
  LIG_ID=$(echo -n "$SMILES" | md5sum | cut -d' ' -f1 | head -c 8)
  echo "Auto-generated ligand ID: $LIG_ID"
fi

echo "Using:"
echo "  PDB      : $PDB"
echo "  MSA      : $MSA"
echo "  OUT_DIR  : $OUT_DIR"
echo "  HOTSPOTS : $HOTSPOTS"
echo "  SMILES   : $SMILES"
echo "  LIG_ID   : $LIG_ID"

# Check for required commands
if ! command -v pdb_tofasta >/dev/null 2>&1; then
  echo "ERROR: pdb_tofasta not found in PATH. Activate the Boltz environment first." >&2
  exit 1
fi

if ! command -v boltz >/dev/null 2>&1; then
  echo "ERROR: boltz not found in PATH. Activate the Boltz environment first." >&2
  exit 1
fi

# Validate input files
if [ ! -f "$PDB" ]; then
  echo "ERROR: PDB file not found: $PDB" >&2
  exit 1
fi

if [ ! -f "$MSA" ]; then
  echo "ERROR: MSA file not found: $MSA" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

echo "Extracting protein sequence from PDB ..."
SEQ=$(pdb_tofasta "$PDB" | awk 'BEGIN{seq=""} !/^>/{gsub(/[[:space:]]+/,"",$0); seq=seq $0} END{print seq}')
if [ -z "${SEQ:-}" ]; then
  echo "ERROR: Failed to extract protein sequence from $PDB" >&2
  exit 1
fi

echo "Sequence length: ${#SEQ}"

# Build contacts list string like: [A, 17], [A, 57], ...
IFS=',' read -r -a _hotspots <<< "$HOTSPOTS"
contacts=""
for idx in "${_hotspots[@]}"; do
  idx_trimmed="${idx//[[:space:]]/}"
  if [ -z "$idx_trimmed" ]; then
    continue
  fi
  if [ -z "$contacts" ]; then
    contacts="[A, $idx_trimmed]"
  else
    contacts="$contacts, [A, $idx_trimmed]"
  fi
done

echo "Contacts: [$contacts]"

DEST_DIR="$OUT_DIR/$LIG_ID"
mkdir -p "$DEST_DIR"
INPUT_YAML="$DEST_DIR/input.yaml"

# Escape double quotes in SMILES for YAML safety
esc_smiles="${SMILES//\"/\\\"}"

# Write input.yaml
cat > "$INPUT_YAML" <<YAML
version: 1
sequences:
  - protein:
      id: A
      sequence: "$SEQ"
      msa: "$MSA"
  - ligand:
      id: B
      smiles: "$esc_smiles"
properties:
  - affinity:
      binder: B
constraints:
  - pocket:
      binder: B
      contacts: [$contacts]
YAML

echo "[$LIG_ID] Running boltz predict ..."
if boltz predict "$INPUT_YAML" --use_potentials --affinity_mw_correction --out_dir "$DEST_DIR"; then
  echo "[$LIG_ID] Done. Output: $DEST_DIR"
else
  echo "[$LIG_ID] ERROR: boltz predict failed" >&2
  exit 1
fi

echo "Screening complete. Results in: $DEST_DIR"


