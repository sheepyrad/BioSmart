"""Generate Figure 13A: log ZIKV NS5 titer by treatment and timepoint."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TABLE_PATH = BASE_DIR / "raw_well_data_all_runs.csv"
OUTPUT_PREFIX = BASE_DIR / "Figure13A"


def format_concentration_label(concentration: str) -> str:
    return concentration.replace(" uM", " \u00b5M")


def concentration_to_um(concentration: str) -> float:
    text = str(concentration).strip()
    if text.endswith("uM"):
        return float(text.replace("uM", "").strip())
    if text.endswith("nM"):
        return float(text.replace("nM", "").strip()) / 1000.0
    return np.nan


def main() -> None:
    df = pd.read_csv(TABLE_PATH)
    if df.empty:
        raise SystemExit(f"No data found: {TABLE_PATH}")

    df["Concentration_uM"] = df["Concentration"].apply(concentration_to_um)
    plot_df = df[
        (df["Included"] == True)
        & (df["Sample_type"].isin(["Treatment", "DMSO control", "Negative control"]))
        & (df["Concentration_uM"].notna())
        & (df["log10_quantity"].notna())
    ].copy()
    if plot_df.empty:
        raise SystemExit("No usable rows for Figure 13A.")

    concentrations = (
        plot_df[plot_df["Sample_type"].isin(["Treatment", "DMSO control"])][
            ["Concentration", "Concentration_uM"]
        ]
        .drop_duplicates()
        .query("Concentration_uM > 0")
        .sort_values("Concentration_uM", ascending=False)
    )
    concentration_order = concentrations["Concentration"].tolist()
    plot_order = ["0 nM"] + concentration_order
    x_labels = ["No treatment"] + [format_concentration_label(c) for c in concentration_order]

    summary = (
        plot_df.groupby(["Timepoint", "Concentration", "Sample_type"], as_index=False)
        .agg(
            Mean_log10_NS5_titer=("log10_quantity", "mean"),
            SD_log10_NS5_titer=("log10_quantity", "std"),
            n=("log10_quantity", "count"),
        )
    )

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.2), dpi=200, sharey=True)
    width = 0.26
    x = np.arange(len(plot_order), dtype=float)
    colors = {"Treatment": "#1f77b4", "DMSO control": "#7f7f7f", "Negative control": "#2ca02c"}

    y_min = np.inf
    y_max = -np.inf
    for timepoint in ["24h", "48h"]:
        sub = summary[summary["Timepoint"] == timepoint]
        for sample in ["Treatment", "DMSO control", "Negative control"]:
            sample_summary = sub[sub["Sample_type"] == sample].set_index("Concentration")
            means = sample_summary.reindex(plot_order)["Mean_log10_NS5_titer"].to_numpy(dtype=float)
            sds = sample_summary.reindex(plot_order)["SD_log10_NS5_titer"].fillna(0).to_numpy(dtype=float)
            if np.isfinite(means - sds).any():
                y_min = min(y_min, float(np.nanmin(means - sds)))
            if np.isfinite(means + sds).any():
                y_max = max(y_max, float(np.nanmax(means + sds)))

    if not np.isfinite(y_min) or not np.isfinite(y_max):
        y_min, y_max = -6.0, -1.0
    pad = max(0.08 * (y_max - y_min), 0.2)
    top_extra = max(0.18 * (y_max - y_min), 0.35)

    for ax, timepoint in zip(axes, ["24h", "48h"]):
        sub = summary[summary["Timepoint"] == timepoint]
        treatment = sub[sub["Sample_type"] == "Treatment"].set_index("Concentration")
        dmso = sub[sub["Sample_type"] == "DMSO control"].set_index("Concentration")
        no_treatment = sub[sub["Sample_type"] == "Negative control"].set_index("Concentration")

        treatment_mean = treatment.reindex(plot_order)["Mean_log10_NS5_titer"].to_numpy(dtype=float)
        treatment_sd = treatment.reindex(plot_order)["SD_log10_NS5_titer"].fillna(0).to_numpy(dtype=float)
        dmso_mean = dmso.reindex(plot_order)["Mean_log10_NS5_titer"].to_numpy(dtype=float)
        dmso_sd = dmso.reindex(plot_order)["SD_log10_NS5_titer"].fillna(0).to_numpy(dtype=float)
        no_treatment_mean = no_treatment.reindex(plot_order)["Mean_log10_NS5_titer"].to_numpy(dtype=float)
        no_treatment_sd = no_treatment.reindex(plot_order)["SD_log10_NS5_titer"].fillna(0).to_numpy(dtype=float)

        ax.bar(x - width, no_treatment_mean, yerr=no_treatment_sd, width=width, capsize=3, color=colors["Negative control"], alpha=0.9, label="No treatment")
        ax.bar(x, treatment_mean, yerr=treatment_sd, width=width, capsize=3, color=colors["Treatment"], alpha=0.9, label="Treatment")
        ax.bar(x + width, dmso_mean, yerr=dmso_sd, width=width, capsize=3, color=colors["DMSO control"], alpha=0.9, label="DMSO control")
        ax.set_title(timepoint, fontsize=14)
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=11)
        ax.tick_params(axis="y", labelsize=11)
        ax.set_xlabel("Compound 45 concentration", fontsize=13)
        ax.grid(axis="y", alpha=0.2)
        ax.set_ylim(0, y_max + pad + top_extra)

    axes[0].set_ylabel("log ZIKV NS5 titer", fontsize=13)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=13, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 0.99))
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(OUTPUT_PREFIX.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(OUTPUT_PREFIX.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
