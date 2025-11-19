#!/usr/bin/env bash

set -euo pipefail

# Simple screening script to run Boltz-2 for a list of ligands (CSV: id,smiles)
# Inputs are adjustable via environment variables prior to invoking the script.

: "${PDB:=/home/conrad_hku/Drug_pipeline/input/NS5_crop_renum.pdb}"
: "${MSA:=/home/conrad_hku/Drug_pipeline/msa/NS5_crop.a3m}"
: "${CSV:=/home/conrad_hku/Drug_pipeline/Boltz_frag_valid/smiles_list.csv}"
: "${OUT_DIR:=/media/data/conrad_hku/boltz_frag_valid}"

# Hotspot residues (1-indexed) used as pocket contacts for binder B
: "${HOTSPOTS:=16,67,138,153,184,185}"

echo "Using:"
echo "  PDB      : $PDB"
echo "  MSA      : $MSA"
echo "  CSV      : $CSV"
echo "  OUT_DIR  : $OUT_DIR"
echo "  HOTSPOTS : $HOTSPOTS"

if ! command -v pdb_tofasta >/dev/null 2>&1; then
  echo "ERROR: pdb_tofasta not found in PATH. Activate the Boltz environment first." >&2
  exit 1
fi

if ! command -v boltz >/dev/null 2>&1; then
  echo "ERROR: boltz not found in PATH. Activate the Boltz environment first." >&2
  exit 1
fi

if [ ! -f "$PDB" ]; then
  echo "ERROR: PDB file not found: $PDB" >&2
  exit 1
fi

if [ ! -f "$MSA" ]; then
  echo "ERROR: MSA file not found: $MSA" >&2
  exit 1
fi

if [ ! -f "$CSV" ]; then
  echo "ERROR: CSV file not found: $CSV" >&2
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

echo "Starting screening ..."

while IFS=, read -r LIG_ID SMILES; do
  # Skip empty or malformed lines
  if [ -z "${LIG_ID:-}" ] || [ -z "${SMILES:-}" ]; then
    continue
  fi

  # Trim simple whitespace from ID
  LIG_ID="${LIG_ID//[$'\t\r\n ']}"
  if [ -z "$LIG_ID" ]; then
    continue
  fi

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
    echo "[$LIG_ID] WARNING: boltz predict failed" >&2
  fi

done < "$CSV"

echo "Screening complete. Results in: $OUT_DIR"


