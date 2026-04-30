#!/usr/bin/env python3
"""
Plot Figure 10 MM-GBSA binding energies and optional residue decomposition.
"""

from itertools import combinations
from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import kruskal, mannwhitneyu


BASE_PATH = Path(__file__).resolve().parent
OUTPUT_PREFIX = BASE_PATH / "Figure10"
REFERENCE_COMPOUND = "Compound 45"
PRIORITY_COMPARISON = "Compound 59"
PDB_RESIDUE_OFFSET = 703  # TRP 130 in the simulated complex maps to TRP 833 in the original protein.
BINDING_AXIS_LABEL_SIZE = 18
BINDING_TICK_LABEL_SIZE = 15
BINDING_SIGNIFICANCE_LABEL_SIZE = 16
DEC_AXIS_LABEL_SIZE = 18
DEC_TICK_LABEL_SIZE = 13
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


def compound_name_from_dir(run_dir: Path) -> str:
    """Convert a folder name like 'Compound 45' to a display label."""
    match = re.fullmatch(r"Compound (\d+)", run_dir.name)
    if not match:
        raise ValueError(f"Could not extract compound number from {run_dir.name}")

    return f"Compound {match.group(1)}"


def compound_sort_key(cpd_name: str) -> int:
    return int(cpd_name.split(" ", 1)[1])


def output_token(cpd_name: str) -> str:
    return cpd_name.replace(" ", "")


def collect_binding_energy_data(base_path: Path) -> dict[str, dict[str, object]]:
    """Collect all BindingEnergy.csv TOTAL values from Compound folders."""
    energy_data: dict[str, dict[str, object]] = {}

    for csv_path in sorted(base_path.glob("Compound */BindingEnergy.csv")):
        run_dir = csv_path.parent
        cpd_name = compound_name_from_dir(run_dir)
        df = pd.read_csv(csv_path)

        if "TOTAL" not in df.columns:
            print(f"Skipping {csv_path}: missing TOTAL column")
            continue

        totals = df["TOTAL"].dropna().to_numpy()
        if totals.size == 0:
            print(f"Skipping {csv_path}: no TOTAL values")
            continue

        energy_data[cpd_name] = {
            "run_dir": run_dir,
            "binding_csv": csv_path,
            "totals": totals,
            "mean": float(np.mean(totals)),
        }
        print(f"{cpd_name}: {totals.size} frames, mean TOTAL = {np.mean(totals):.3f}")

    return dict(sorted(energy_data.items(), key=lambda item: compound_sort_key(item[0])))


def plot_binding_energy_boxplot(
    energy_data: dict[str, dict[str, object]], output_prefix: Path
) -> None:
    labels = list(energy_data.keys())
    totals = [energy_data[label]["totals"] for label in labels]
    colors = plt.cm.tab10(np.linspace(0, 1, len(labels)))

    fig, ax = plt.subplots(figsize=(12, 7))
    tick_labels = [label.removeprefix("Compound ") for label in labels]
    boxplot = ax.boxplot(totals, tick_labels=tick_labels, patch_artist=True)

    for patch, color in zip(boxplot["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)

    ax.set_xlabel("Compound ID", fontsize=BINDING_AXIS_LABEL_SIZE)
    ax.set_ylabel("Binding free energy (kcal/mol)", fontsize=BINDING_AXIS_LABEL_SIZE)
    ax.tick_params(axis="both", labelsize=BINDING_TICK_LABEL_SIZE)
    ax.yaxis.grid(True, linestyle="--", alpha=0.25)
    ax.set_axisbelow(True)

    if REFERENCE_COMPOUND in energy_data:
        reference_index = labels.index(REFERENCE_COMPOUND) + 1
        comparison_labels = [label for label in labels if label != REFERENCE_COMPOUND]
        if PRIORITY_COMPARISON in comparison_labels:
            comparison_labels.remove(PRIORITY_COMPARISON)
            comparison_labels.insert(0, PRIORITY_COMPARISON)
        raw_p_values = [
            mannwhitneyu(
                energy_data[REFERENCE_COMPOUND]["totals"],
                energy_data[label]["totals"],
                alternative="less",
            ).pvalue
            for label in comparison_labels
        ]
        adjusted_p_values = holm_adjust_pvalues(raw_p_values)
        all_values = np.concatenate(totals)
        y_min = float(np.min(all_values))
        y_max = float(np.max(all_values))
        y_span = y_max - y_min
        bracket_start = y_max + y_span * 0.025
        bracket_step = y_span * 0.055
        tick_height = y_span * 0.015

        for index, (label, adjusted_p) in enumerate(zip(comparison_labels, adjusted_p_values)):
            stars = significance_stars(adjusted_p)
            if not stars:
                continue

            x_other = labels.index(label) + 1
            bracket_y = bracket_start + index * bracket_step
            ax.plot(
                [x_other, x_other, reference_index, reference_index],
                [bracket_y, bracket_y + tick_height, bracket_y + tick_height, bracket_y],
                color="black",
                linewidth=1,
            )
            ax.text(
                (x_other + reference_index) / 2,
                bracket_y + tick_height,
                stars,
                ha="center",
                va="bottom",
                fontsize=BINDING_SIGNIFICANCE_LABEL_SIZE,
                fontweight="bold",
            )
        ax.set_ylim(
            y_min - y_span * 0.08,
            bracket_start + len(comparison_labels) * bracket_step + y_span * 0.08,
        )

    plt.xticks(rotation=45, ha="right", fontsize=BINDING_TICK_LABEL_SIZE)
    plt.tight_layout()

    png_path = output_prefix.with_name(f"{output_prefix.name}_binding_energy_boxplot.png")
    pdf_path = output_prefix.with_name(f"{output_prefix.name}_binding_energy_boxplot.pdf")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    print(f"\nSaved binding energy boxplot to {png_path} and {pdf_path}")
    plt.close(fig)


def holm_adjust_pvalues(p_values: list[float]) -> list[float]:
    """Return Holm-Bonferroni adjusted p-values in the original order."""
    indexed_p_values = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(p_values)
    previous_adjusted = 0.0
    total_tests = len(p_values)

    for rank, (original_index, p_value) in enumerate(indexed_p_values):
        adjusted_p = min((total_tests - rank) * p_value, 1.0)
        adjusted_p = max(adjusted_p, previous_adjusted)
        adjusted[original_index] = adjusted_p
        previous_adjusted = adjusted_p

    return adjusted


def significance_stars(p_value: float) -> str:
    if p_value < 0.0001:
        return "****"
    if p_value < 0.001:
        return "***"
    if p_value < 0.01:
        return "**"
    if p_value < 0.05:
        return "*"
    return ""


def run_binding_energy_statistics(
    energy_data: dict[str, dict[str, object]], output_prefix: Path
) -> None:
    """
    Run non-parametric statistics for binding energies.

    Kruskal-Wallis is used as the omnibus test because the distributions do not
    need to be normal. Pairwise Mann-Whitney U tests are one-sided in the lower
    binding free energy direction, then Holm-corrected to control family-wise
    error across all compound comparisons.
    """
    labels = list(energy_data.keys())
    totals = [energy_data[label]["totals"] for label in labels]
    h_statistic, omnibus_p = kruskal(*totals)

    summary_rows = []
    for label, values in zip(labels, totals):
        summary_rows.append(
            {
                "compound": label,
                "n_frames": len(values),
                "mean": np.mean(values),
                "median": np.median(values),
                "std": np.std(values, ddof=1),
                "iqr": np.percentile(values, 75) - np.percentile(values, 25),
                "min": np.min(values),
                "max": np.max(values),
            }
        )

    pairwise_rows = []
    raw_p_values = []
    for label_a, label_b in combinations(labels, 2):
        values_a = energy_data[label_a]["totals"]
        values_b = energy_data[label_b]["totals"]
        mean_a = np.mean(values_a)
        mean_b = np.mean(values_b)
        if mean_a <= mean_b:
            lower_label = label_a
            higher_label = label_b
            lower_values = values_a
            higher_values = values_b
        else:
            lower_label = label_b
            higher_label = label_a
            lower_values = values_b
            higher_values = values_a

        u_statistic, p_value = mannwhitneyu(
            lower_values,
            higher_values,
            alternative="less",
        )
        n_a = len(lower_values)
        n_b = len(higher_values)
        rank_biserial = (2 * u_statistic / (n_a * n_b)) - 1
        raw_p_values.append(p_value)
        pairwise_rows.append(
            {
                "lower_mean_compound": lower_label,
                "higher_mean_compound": higher_label,
                "alternative": f"{lower_label} has lower binding free energy than {higher_label}",
                "u_statistic": u_statistic,
                "p_value": p_value,
                "rank_biserial_effect": rank_biserial,
                "mean_diff_lower_minus_higher": np.mean(lower_values) - np.mean(higher_values),
                "median_diff_lower_minus_higher": np.median(lower_values) - np.median(higher_values),
            }
        )

    adjusted_p_values = holm_adjust_pvalues(raw_p_values)
    for row, adjusted_p in zip(pairwise_rows, adjusted_p_values):
        row["p_holm"] = adjusted_p
        row["significant_holm_0.05"] = adjusted_p < 0.05

    summary_df = pd.DataFrame(summary_rows).sort_values("mean")
    pairwise_df = pd.DataFrame(pairwise_rows).sort_values("p_holm")

    summary_csv = output_prefix.with_name(f"{output_prefix.name}_binding_energy_summary_stats.csv")
    pairwise_csv = output_prefix.with_name(f"{output_prefix.name}_binding_energy_pairwise_mannwhitney.csv")
    stats_txt = output_prefix.with_name(f"{output_prefix.name}_binding_energy_statistics.txt")

    summary_df.to_csv(summary_csv, index=False)
    pairwise_df.to_csv(pairwise_csv, index=False)

    with stats_txt.open("w") as handle:
        handle.write("Non-parametric binding energy statistics\n")
        handle.write("=======================================\n\n")
        handle.write("Omnibus test: Kruskal-Wallis H-test across all compounds\n")
        handle.write(f"H statistic: {h_statistic:.6g}\n")
        handle.write(f"p-value: {omnibus_p:.6g}\n")
        handle.write(
            "Interpretation: "
            + ("significant differences detected" if omnibus_p < 0.05 else "no significant difference detected")
            + " at alpha=0.05.\n\n"
        )
        handle.write(
            "Pairwise test: one-sided Mann-Whitney U in the lower binding free "
            "energy direction with Holm-Bonferroni correction\n"
        )
        handle.write(pairwise_df.to_string(index=False))
        handle.write("\n")

    print("\nNon-parametric binding energy statistics")
    print(f"Kruskal-Wallis H = {h_statistic:.4f}, p = {omnibus_p:.4e}")
    print(f"Saved summary statistics to {summary_csv}")
    print(f"Saved pairwise Mann-Whitney results to {pairwise_csv}")
    print(f"Saved statistics report to {stats_txt}")


def parse_residue_id(resid: str) -> tuple[str, str, str, int]:
    """Parse residue ids like R:A:SER:182."""
    parts = resid.split(":")
    if len(parts) != 4:
        raise ValueError(f"Unexpected residue id format: {resid}")

    role, chain, residue_name, residue_number = parts
    return role, chain, residue_name, int(residue_number)


def format_residue_label(residue_name: str, residue_number: int) -> str:
    residue_code = AMINO_ACID_3_TO_1.get(residue_name.upper(), residue_name)
    return f"{residue_code}{residue_number}"


def plot_dec_for_best_compound(
    best_cpd_name: str,
    best_run_dir: Path,
    residue_offset: int,
    output_prefix: Path,
) -> None:
    dec_path = best_run_dir / "ligand" / "Dec.csv"
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
    ax.set_xlabel("PDB residue number", fontsize=DEC_AXIS_LABEL_SIZE)
    ax.set_ylabel("Binding free energy (kcal/mol)", fontsize=DEC_AXIS_LABEL_SIZE)
    ax.tick_params(axis="y", labelsize=DEC_TICK_LABEL_SIZE)
    ax.yaxis.grid(True, linestyle="--", alpha=0.25)
    ax.set_axisbelow(True)

    plt.xticks(rotation=45, ha="right", fontsize=DEC_TICK_LABEL_SIZE)
    plt.tight_layout()

    compound_token = output_token(best_cpd_name)
    png_path = output_prefix.with_name(f"{output_prefix.name}_{compound_token}_dec_remapped.png")
    pdf_path = output_prefix.with_name(f"{output_prefix.name}_{compound_token}_dec_remapped.pdf")
    csv_path = output_prefix.with_name(f"{output_prefix.name}_{compound_token}_dec_remapped.csv")

    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(pdf_path, bbox_inches="tight")
    per_residue.to_csv(csv_path, index=False)
    print(f"Saved remapped DEC plot to {png_path} and {pdf_path}")
    print(f"Saved remapped per-residue DEC table to {csv_path}")
    plt.close(fig)


def main() -> None:
    energy_data = collect_binding_energy_data(BASE_PATH)
    if not energy_data:
        raise RuntimeError(f"No BindingEnergy.csv files found under {BASE_PATH}")

    plot_binding_energy_boxplot(energy_data, OUTPUT_PREFIX)
    run_binding_energy_statistics(energy_data, OUTPUT_PREFIX)

    best_cpd_name, best_info = min(energy_data.items(), key=lambda item: item[1]["mean"])
    best_mean = best_info["mean"]
    print(f"\nLowest mean binding energy: {best_cpd_name} ({best_mean:.3f} kcal/mol)")

    dec_path = best_info["run_dir"] / "ligand" / "Dec.csv"
    if not dec_path.exists():
        print(f"Skipping residue decomposition plot: {dec_path} not found.")
        return

    residue_offset = PDB_RESIDUE_OFFSET
    print(
        "Using manual PDB residue-number mapping: "
        f"complex residue N maps to original protein residue N + {residue_offset}."
    )

    plot_dec_for_best_compound(
        best_cpd_name=best_cpd_name,
        best_run_dir=best_info["run_dir"],
        residue_offset=residue_offset,
        output_prefix=OUTPUT_PREFIX,
    )


if __name__ == "__main__":
    main()
