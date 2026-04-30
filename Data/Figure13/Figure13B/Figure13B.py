"""Generate Figure 13B: 50 and 100 uM log10 viral copies vs DMSO control."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
TABLE_PATH = BASE_DIR / "raw_well_data_all_runs.csv"
OUTPUT_PREFIX = BASE_DIR / "Figure13B"
CONCENTRATION_TO_UM = {
    "100 uM": 100.0,
    "50 uM": 50.0,
}


def main() -> None:
    all_raw = pd.read_csv(TABLE_PATH)
    wanted_concentrations = set(CONCENTRATION_TO_UM)
    dmso = all_raw[
        (all_raw["Included"])
        & (all_raw["Sample_type"] == "DMSO control")
        & (all_raw["Concentration"].isin(wanted_concentrations))
        & (all_raw["log10_quantity"].notna())
    ].copy()
    treatment = all_raw[
        (all_raw["Included"])
        & (all_raw["Sample_type"] == "Treatment")
        & (all_raw["Concentration"].isin(wanted_concentrations))
        & (all_raw["log10_quantity"].notna())
    ].copy()
    if treatment.empty or dmso.empty:
        raise SystemExit("No usable rows for Figure 13B.")

    concentration_order = sorted(
        treatment["Concentration"].unique().tolist(),
        key=lambda concentration: CONCENTRATION_TO_UM[concentration],
    )

    agg_dmso = (
        dmso.groupby(["Timepoint", "Concentration"], as_index=False)
        .agg(Mean_log10=("log10_quantity", "mean"), SD_log10=("log10_quantity", "std"), n=("Well", "count"))
    )
    agg_treatment = (
        treatment.groupby(["Timepoint", "Concentration"], as_index=False)
        .agg(Mean_log10=("log10_quantity", "mean"), SD_log10=("log10_quantity", "std"), n=("Well", "count"))
    )

    def values(summary: pd.DataFrame, timepoint: str, concentration: str) -> tuple[float, float]:
        row = summary[(summary["Timepoint"] == timepoint) & (summary["Concentration"] == concentration)]
        if row.empty or pd.isna(row["Mean_log10"].iloc[0]):
            return np.nan, 0.0
        sd = row["SD_log10"].iloc[0]
        return float(row["Mean_log10"].iloc[0]), float(sd) if pd.notna(sd) else 0.0

    fig, axes = plt.subplots(1, 2, figsize=(8.4, 4.9), dpi=200, sharey=True)
    width = 0.36
    x = np.arange(len(concentration_order), dtype=float)

    for ax, timepoint in zip(axes, ["24h", "48h"]):
        means_dmso: list[float] = []
        sd_dmso: list[float] = []
        means_treatment: list[float] = []
        sd_treatment: list[float] = []
        for concentration in concentration_order:
            dmso_mean, dmso_sd = values(agg_dmso, timepoint, concentration)
            treatment_mean, treatment_sd = values(agg_treatment, timepoint, concentration)
            means_dmso.append(dmso_mean)
            sd_dmso.append(dmso_sd)
            means_treatment.append(treatment_mean)
            sd_treatment.append(treatment_sd)

        x_dmso = x - width / 2
        x_treatment = x + width / 2
        ax.bar(x_dmso, means_dmso, width=width, yerr=sd_dmso, capsize=3, color="#7f7f7f", alpha=0.92, label="DMSO control")
        ax.bar(x_treatment, means_treatment, width=width, yerr=sd_treatment, capsize=3, color="#1f77b4", alpha=0.92, label="Treatment")

        for index, _concentration in enumerate(concentration_order):
            dmso_mean, dmso_sd = means_dmso[index], sd_dmso[index]
            treatment_mean, treatment_sd = means_treatment[index], sd_treatment[index]
            if not np.isfinite(dmso_mean) or not np.isfinite(treatment_mean):
                continue
            delta = dmso_mean - treatment_mean
            y_bracket = max(dmso_mean + dmso_sd, treatment_mean + treatment_sd) + 0.12
            ax.plot(
                [x_dmso[index], x_dmso[index], x_treatment[index], x_treatment[index]],
                [y_bracket, y_bracket + 0.06, y_bracket + 0.06, y_bracket],
                color="black",
                linewidth=0.9,
            )
            ax.text(x[index], y_bracket + 0.08, rf"$\Delta\log_{{10}}$={delta:.2f}", ha="center", va="bottom", fontsize=8)

        ax.set_xticks(x)
        ax.set_xticklabels([c.replace(" uM", " \u00b5M") for c in concentration_order])
        ax.set_xlabel("Compound 45 concentration")
        ax.set_title(timepoint)
        ax.grid(axis="y", alpha=0.2)

    axes[0].set_ylabel("Log ZIKV NS5 Titer")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=10, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 0.99))
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(OUTPUT_PREFIX.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(OUTPUT_PREFIX.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
