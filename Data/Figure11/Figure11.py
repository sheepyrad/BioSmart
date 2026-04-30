#!/usr/bin/env python3
"""Generate Figure 11 residue decomposition outputs for Compound 45."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BASE_PATH = Path(__file__).resolve().parent
COMPOUND_NAME = "Compound 45"
OUTPUT_PREFIX = BASE_PATH / "Figure11_Compound45"
PDB_RESIDUE_OFFSET = 703  # TRP 130 in the simulated complex maps to TRP 833 in the original protein.
AXIS_LABEL_SIZE = 18
TICK_LABEL_SIZE = 13
AMINO_ACID_3_TO_1 = {
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
}


def parse_residue_id(resid: str) -> tuple[str, str, str, int]:
    """Parse residue IDs like R:A:SER:182."""
    parts = resid.split(":")
    if len(parts) != 4:
        raise ValueError(f"Unexpected residue ID format: {resid}")

    role, chain, residue_name, residue_number = parts
    return role, chain, residue_name, int(residue_number)


def format_residue_label(residue_name: str, residue_number: int) -> str:
    residue_code = AMINO_ACID_3_TO_1.get(residue_name.upper(), residue_name)
    return f"{residue_code}{residue_number}"


def summarize_residue_decomposition(dec_path: Path, residue_offset: int) -> pd.DataFrame:
    if not dec_path.exists():
        raise FileNotFoundError(f"Could not find decomposition CSV: {dec_path}")

    dec_df = pd.read_csv(dec_path, index_col=0)
    required_columns = {"resid", "TOTAL"}
    missing_columns = required_columns - set(dec_df.columns)
    if missing_columns:
        raise ValueError(f"{dec_path} is missing required columns: {sorted(missing_columns)}")

    residue_records = dec_df["resid"].apply(parse_residue_id)
    dec_df["role"] = residue_records.apply(lambda value: value[0])
    dec_df["chain"] = residue_records.apply(lambda value: value[1])
    dec_df["residue_name"] = residue_records.apply(lambda value: value[2])
    dec_df["complex_residue_number"] = residue_records.apply(lambda value: value[3])
    dec_df = dec_df[dec_df["role"] == "R"].copy()
    if dec_df.empty:
        raise ValueError(f"{dec_path} did not contain receptor residue decomposition rows.")

    dec_df["full_residue_number"] = dec_df["complex_residue_number"] + residue_offset
    per_residue = (
        dec_df.groupby(
            ["chain", "residue_name", "complex_residue_number", "full_residue_number"],
            as_index=False,
        )
        .agg(mean_total=("TOTAL", "mean"), std_total=("TOTAL", "std"), n_frames=("TOTAL", "size"))
        .sort_values("full_residue_number")
    )
    per_residue["label"] = per_residue.apply(
        lambda row: format_residue_label(row["residue_name"], row["full_residue_number"]),
        axis=1,
    )
    return per_residue


def plot_residue_decomposition(per_residue: pd.DataFrame, output_prefix: Path) -> None:
    fig_width = max(12, len(per_residue) * 0.22)
    fig, ax = plt.subplots(figsize=(fig_width, 7))
    colors = np.where(per_residue["mean_total"] < 0, "#4C956C", "#C65D57")

    ax.bar(
        per_residue["label"],
        per_residue["mean_total"],
        yerr=per_residue["std_total"],
        color=colors,
        alpha=0.85,
        capsize=2,
    )
    ax.axhline(y=0, color="black", linewidth=0.8)
    ax.set_xlabel("PDB residue number", fontsize=AXIS_LABEL_SIZE)
    ax.set_ylabel("Binding free energy (kcal/mol)", fontsize=AXIS_LABEL_SIZE)
    ax.tick_params(axis="y", labelsize=TICK_LABEL_SIZE)
    ax.yaxis.grid(True, linestyle="--", alpha=0.25)
    ax.set_axisbelow(True)

    plt.xticks(rotation=45, ha="right", fontsize=TICK_LABEL_SIZE)
    plt.tight_layout()

    png_path = output_prefix.with_name(f"{output_prefix.name}_dec_remapped.png")
    pdf_path = output_prefix.with_name(f"{output_prefix.name}_dec_remapped.pdf")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    print(f"Saved remapped DEC plot to {png_path} and {pdf_path}")
    plt.close(fig)


def main() -> None:
    dec_path = BASE_PATH / COMPOUND_NAME / "ligand" / "Dec.csv"
    print(
        "Using manual PDB residue-number mapping: "
        f"complex residue N maps to original protein residue N + {PDB_RESIDUE_OFFSET}."
    )

    per_residue = summarize_residue_decomposition(dec_path, PDB_RESIDUE_OFFSET)
    csv_path = OUTPUT_PREFIX.with_name(f"{OUTPUT_PREFIX.name}_dec_remapped.csv")
    per_residue.to_csv(csv_path, index=False)
    print(f"Saved remapped per-residue DEC table to {csv_path}")

    plot_residue_decomposition(per_residue, OUTPUT_PREFIX)


if __name__ == "__main__":
    main()
