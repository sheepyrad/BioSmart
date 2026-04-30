"""Generate Figure 14: Compound 45 ZIKV NS5 inhibition dose response."""

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
SUMMARY_TABLE = BASE_DIR / "Figure14_timepoint_dose_response_summary.csv"
IC50_TABLE = BASE_DIR / "Figure14_timepoint_ic50_estimates.csv"
OUTPUT_PREFIX = BASE_DIR / "Figure14"


@dataclass(frozen=True)
class DoseResponseFit:
    ic50_uM: float
    hill_slope: float

    def predict_pct_inhibition(self, concentration_uM: np.ndarray) -> np.ndarray:
        concentration_uM = np.asarray(concentration_uM, dtype=float)
        return 100.0 / (1.0 + (self.ic50_uM / concentration_uM) ** self.hill_slope)


def main() -> None:
    summary = pd.read_csv(SUMMARY_TABLE)
    ic50 = pd.read_csv(IC50_TABLE)
    if summary.empty or ic50.empty:
        raise SystemExit("Missing Figure 14 dose-response data.")

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 5.2), dpi=200, sharex=True, sharey=True)
    colors = {"24h": "#1f77b4", "48h": "#d62728"}
    yerr_all = summary["SD_Inhibition"].fillna(0)
    y_min = float((summary["Mean_Inhibition"] - yerr_all).min())
    y_max = float((summary["Mean_Inhibition"] + yerr_all).max())
    y_lo = np.floor((min(0.0, y_min) - 5.0) / 10.0) * 10.0
    y_hi = np.ceil((max(100.0, y_max) + 5.0) / 10.0) * 10.0

    for ax, timepoint in zip(axes, ["24h", "48h"]):
        sub = summary[summary["Timepoint"] == timepoint].sort_values("Concentration_uM")
        if sub.empty:
            ax.set_title(f"{timepoint} (no data)")
            continue

        x = np.log10(sub["Concentration_uM"].to_numpy(dtype=float))
        y = sub["Mean_Inhibition"].to_numpy(dtype=float)
        yerr = sub["SD_Inhibition"].fillna(0).to_numpy(dtype=float)
        fit_row = ic50[ic50["Timepoint"] == timepoint].iloc[0]
        fit = DoseResponseFit(
            ic50_uM=float(fit_row["IC50_uM"]),
            hill_slope=float(fit_row["Hill_slope"]),
        )
        smooth_x = np.logspace(np.log10(sub["Concentration_uM"].min()), np.log10(sub["Concentration_uM"].max()), 300)
        smooth_y = fit.predict_pct_inhibition(smooth_x)

        ax.errorbar(
            x,
            y,
            yerr=yerr,
            fmt="o",
            capsize=3,
            markersize=4.5,
            color=colors[timepoint],
            label="Mean inhibition +/- SD",
        )
        ax.plot(
            np.log10(smooth_x),
            smooth_y,
            color=colors[timepoint],
            linewidth=2,
            linestyle="-",
            label=rf"Hill fit ($IC_{{50}}$ = {fit.ic50_uM:.2f} uM)",
        )
        ax.set_title(timepoint, fontsize=15)
        ax.grid(alpha=0.2)
        ax.tick_params(axis="both", labelsize=12)
        ax.legend(frameon=False, fontsize=11, loc="upper left")

    for ax in axes:
        ax.set_xlabel("Log[Compound 45 (uM)]", fontsize=14)
    axes[0].set_ylabel("ZIKV NS5 inhibition vs DMSO control (%)", fontsize=14)
    axes[0].set_ylim(y_lo, y_hi)

    fig.tight_layout()
    fig.savefig(OUTPUT_PREFIX.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(OUTPUT_PREFIX.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
