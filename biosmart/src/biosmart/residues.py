"""Residues a scientist can click to define a Pocket.

The list comes from a Target already stored in the inputs folder. It does not
include a host path.
"""

from __future__ import annotations

from pathlib import Path

_AMINO = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
    "SEC": "U",
    "PYL": "O",
    "ASX": "B",
    "GLX": "Z",
    "UNK": "X",
}


class ResidueError(ValueError):
    """The Target structure could not be read as residues."""


def read_structure(path: Path) -> dict[str, object]:
    """Return chains and residues for one Target structure."""
    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ResidueError("The Target structure could not be read") from exc
    suffix = path.suffix.lower()
    if suffix in {".cif", ".mmcif"} or "_atom_site." in text:
        chains = _mmcif_chains(text)
    else:
        chains = _pdb_chains(text)
    residues: list[dict[str, str]] = []
    for chain in chains:
        residues.extend(chain["residues"])
    return {"chains": chains, "residues": residues}


def sequence_for(parsed: dict[str, object], residues: list[str]) -> str:
    """Sequence of the chain that holds the selected residues."""
    chains = parsed.get("chains")
    if not isinstance(chains, list):
        return ""
    preferred = ""
    if residues:
        preferred = residues[0].split(":", 1)[0]
    for chain in chains:
        if isinstance(chain, dict) and chain.get("chain") == preferred:
            sequence = chain.get("sequence")
            return sequence if isinstance(sequence, str) else ""
    for chain in chains:
        if isinstance(chain, dict) and isinstance(chain.get("sequence"), str):
            return chain["sequence"]
    return ""


def _pdb_chains(text: str) -> list[dict[str, object]]:
    order: list[str] = []
    chains: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("ATOM") or len(line) < 26:
            continue
        name = line[17:20].strip().upper()
        letter = _AMINO.get(name)
        if letter is None:
            continue
        chain_id = (line[21] if len(line) > 21 else " ").strip() or "A"
        number = line[22:26].strip()
        if not number.isdigit():
            continue
        residue_id = f"{chain_id}:{number}"
        if residue_id in seen:
            continue
        seen.add(residue_id)
        chain = chains.get(chain_id)
        if chain is None:
            chain = {"chain": chain_id, "sequence": "", "residues": []}
            chains[chain_id] = chain
            order.append(chain_id)
        residues = chain["residues"]
        if isinstance(residues, list):
            residues.append({"id": residue_id, "name": name, "chain": chain_id})
        chain["sequence"] = str(chain["sequence"]) + letter
    return [chains[chain_id] for chain_id in order]


def _mmcif_chains(text: str) -> list[dict[str, object]]:
    columns = _atom_site_rows(text)
    if columns is None:
        return []
    headers, rows = columns
    index = {header: position for position, header in enumerate(headers)}

    def cell(row: list[str], *names: str) -> str:
        for name in names:
            position = index.get(name)
            if position is not None and position < len(row):
                return row[position]
        return ""

    order: list[str] = []
    chains: dict[str, dict[str, object]] = {}
    seen: set[str] = set()
    for row in rows:
        group = cell(row, "_atom_site.group_PDB").upper()
        if group and group != "ATOM":
            continue
        name = cell(row, "_atom_site.label_comp_id", "_atom_site.auth_comp_id").upper()
        letter = _AMINO.get(name)
        if letter is None:
            continue
        chain_id = cell(row, "_atom_site.auth_asym_id", "_atom_site.label_asym_id").strip() or "A"
        number = cell(row, "_atom_site.auth_seq_id", "_atom_site.label_seq_id").strip()
        if not number.isdigit():
            continue
        residue_id = f"{chain_id}:{number}"
        if residue_id in seen:
            continue
        seen.add(residue_id)
        chain = chains.get(chain_id)
        if chain is None:
            chain = {"chain": chain_id, "sequence": "", "residues": []}
            chains[chain_id] = chain
            order.append(chain_id)
        residues = chain["residues"]
        if isinstance(residues, list):
            residues.append({"id": residue_id, "name": name, "chain": chain_id})
        chain["sequence"] = str(chain["sequence"]) + letter
    return [chains[chain_id] for chain_id in order]


def _atom_site_rows(text: str) -> tuple[list[str], list[list[str]]] | None:
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != "loop_":
            index += 1
            continue
        index += 1
        headers: list[str] = []
        while index < len(lines) and lines[index].strip().startswith("_"):
            headers.append(lines[index].split()[0])
            index += 1
        if not any(header.startswith("_atom_site.") for header in headers):
            continue
        rows: list[list[str]] = []
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped or stripped in {"#", "loop_"} or stripped.startswith(("data_", "_")):
                break
            rows.append(stripped.split())
            index += 1
        return headers, rows
    return None
