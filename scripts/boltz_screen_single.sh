#!/usr/bin/env bash

set -euo pipefail

# Ligand screening script to run Boltz-2 for SMILES strings
# Supports single SMILES or a file with multiple SMILES (one per line)
# Usage: boltz_screen_single.sh --smiles "SMILES_STRING" [OPTIONS]
#    OR: boltz_screen_single.sh --smiles-file FILE.txt [OPTIONS]

# Default values (can be overridden via CLI flags or environment variables)
: "${PDB:=/home/conrad_hku/Drug_pipeline/input/NS5_crop_renum.pdb}"
: "${MSA:=/home/conrad_hku/Drug_pipeline/msa/NS5_crop.a3m}"
: "${OUT_DIR:=/media/data/conrad_hku/boltz_frag_valid}"
: "${HOTSPOTS:=16,67,138,153,184,185}"

SMILES=""
SMILES_FILE=""
LIG_ID=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --smiles|-s)
      SMILES="$2"
      shift 2
      ;;
    --smiles-file|-f)
      SMILES_FILE="$2"
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
    --no-hotspots)
      HOTSPOTS=""
      shift
      ;;
    --help)
      echo "Usage: $0 --smiles SMILES_STRING [OPTIONS]"
      echo "   OR: $0 --smiles-file FILE.txt [OPTIONS]"
      echo ""
      echo "Required (one of):"
      echo "  --smiles, -s SMILES_STRING    Single SMILES string to screen"
      echo "  --smiles-file, -f FILE        Text file with SMILES (one per line)"
      echo "                                Lines can be: SMILES or ID<TAB>SMILES or ID SMILES"
      echo ""
      echo "Optional:"
      echo "  --id, -i LIGAND_ID            Ligand ID (only for single --smiles mode)"
      echo "  --pdb, -p PDB_FILE            PDB file path (default: \$PDB or $PDB)"
      echo "  --msa, -m MSA_FILE            MSA file path (default: \$MSA or $MSA)"
      echo "  --out-dir, -o OUT_DIR         Output directory (default: \$OUT_DIR or $OUT_DIR)"
      echo "  --hotspots, -h RESIDUES       Comma-separated hotspot residues (default: \$HOTSPOTS or $HOTSPOTS)"
      echo "  --no-hotspots                 Remove hotspot constraints (overrides --hotspots)"
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

# Validate: need either --smiles or --smiles-file, but not both
if [ -n "$SMILES" ] && [ -n "$SMILES_FILE" ]; then
  echo "ERROR: Cannot use both --smiles and --smiles-file. Choose one." >&2
  exit 1
fi

if [ -z "$SMILES" ] && [ -z "$SMILES_FILE" ]; then
  echo "ERROR: --smiles or --smiles-file is required" >&2
  echo "Use --help for usage information" >&2
  exit 1
fi

# Validate SMILES file exists
if [ -n "$SMILES_FILE" ] && [ ! -f "$SMILES_FILE" ]; then
  echo "ERROR: SMILES file not found: $SMILES_FILE" >&2
  exit 1
fi

echo "Using:"
echo "  PDB      : $PDB"
echo "  MSA      : $MSA"
echo "  OUT_DIR  : $OUT_DIR"
echo "  HOTSPOTS : ${HOTSPOTS:-<none>}"
if [ -n "$SMILES" ]; then
  echo "  SMILES   : $SMILES"
  echo "  LIG_ID   : ${LIG_ID:-<auto>}"
else
  echo "  SMILES_FILE : $SMILES_FILE"
fi

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
contacts=""
if [ -n "$HOTSPOTS" ]; then
  IFS=',' read -r -a _hotspots <<< "$HOTSPOTS"
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
fi

if [ -n "$contacts" ]; then
  echo "Contacts: [$contacts]"
else
  echo "Contacts: (none - hotspot constraints disabled)"
fi

# Function to run boltz prediction for a single SMILES
run_boltz_single() {
  local smiles="$1"
  local lig_id="$2"
  
  # Generate ligand ID from SMILES hash if not provided
  if [ -z "$lig_id" ]; then
    lig_id=$(echo -n "$smiles" | md5sum | cut -d' ' -f1 | head -c 8)
    echo "[$lig_id] Auto-generated ligand ID for SMILES: $smiles"
  fi
  
  local dest_dir="$OUT_DIR/$lig_id"
  mkdir -p "$dest_dir"
  local input_yaml="$dest_dir/input.yaml"
  
  # Escape double quotes in SMILES for YAML safety
  local esc_smiles="${smiles//\"/\\\"}"
  
  # Write input.yaml
  if [ -n "$contacts" ]; then
    cat > "$input_yaml" <<YAML
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
  else
    cat > "$input_yaml" <<YAML
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
YAML
  fi
  
  echo "[$lig_id] Running boltz predict ..."
  if boltz predict "$input_yaml" --out_dir "$dest_dir" --use_potentials; then
    echo "[$lig_id] Done. Output: $dest_dir"
    return 0
  else
    echo "[$lig_id] ERROR: boltz predict failed" >&2
    return 1
  fi
}

# Main execution
if [ -n "$SMILES" ]; then
  # Single SMILES mode
  if [ -z "$LIG_ID" ]; then
    LIG_ID=$(echo -n "$SMILES" | md5sum | cut -d' ' -f1 | head -c 8)
    echo "Auto-generated ligand ID: $LIG_ID"
  fi
  
  run_boltz_single "$SMILES" "$LIG_ID"
  echo "Screening complete. Results in: $OUT_DIR/$LIG_ID"
else
  # File mode: process each line
  echo ""
  echo "=========================================="
  echo "Processing SMILES file: $SMILES_FILE"
  echo "=========================================="
  
  total_count=0
  success_count=0
  fail_count=0
  
  while IFS= read -r line || [ -n "$line" ]; do
    # Skip empty lines and comments
    line="${line%%#*}"  # Remove comments
    line="${line#"${line%%[![:space:]]*}"}"  # Trim leading whitespace
    line="${line%"${line##*[![:space:]]}"}"  # Trim trailing whitespace
    
    if [ -z "$line" ]; then
      continue
    fi
    
    ((total_count++)) || true
    
    # Parse line: can be "SMILES" or "ID<TAB>SMILES" or "ID SMILES"
    local_id=""
    local_smiles=""
    
    if [[ "$line" == *$'\t'* ]]; then
      # Tab-separated: ID<TAB>SMILES
      local_id=$(echo "$line" | cut -f1)
      local_smiles=$(echo "$line" | cut -f2-)
    elif [[ "$line" == *" "* ]]; then
      # Space-separated: ID SMILES (first word is ID, rest is SMILES)
      local_id=$(echo "$line" | awk '{print $1}')
      local_smiles=$(echo "$line" | awk '{$1=""; print $0}' | sed 's/^ *//')
    else
      # Just SMILES
      local_smiles="$line"
    fi
    
    # Validate SMILES is not empty
    if [ -z "$local_smiles" ]; then
      echo "[Line $total_count] WARNING: Empty SMILES, skipping"
      continue
    fi
    
    echo ""
    echo "=========================================="
    echo "[Line $total_count] Processing: ${local_id:-<auto-id>} -> $local_smiles"
    echo "=========================================="
    
    if run_boltz_single "$local_smiles" "$local_id"; then
      ((success_count++)) || true
    else
      ((fail_count++)) || true
      echo "[Line $total_count] WARNING: Failed, continuing with next..."
    fi
    
  done < "$SMILES_FILE"
  
  echo ""
  echo "=========================================="
  echo "Batch processing complete!"
  echo "  Total:     $total_count"
  echo "  Success:   $success_count"
  echo "  Failed:    $fail_count"
  echo "  Output in: $OUT_DIR"
  echo "=========================================="
fi
