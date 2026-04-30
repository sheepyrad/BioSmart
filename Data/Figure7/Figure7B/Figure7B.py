"""Generate Figure 7B: cumulative compounds above Boltz score thresholds."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "Figure7_boltz_scores_cumulative_thresholds.csv"
OUTPUT_PREFIX = BASE_DIR / "Figure7B"
THRESHOLDS = (0.5, 0.6, 0.7, 0.8)


def main() -> None:
    scores = pd.read_csv(DATA_PATH).sort_values("molecules_processed").reset_index(drop=True)
    if scores.empty:
        raise SystemExit(f"No data found: {DATA_PATH}")

    required_columns = {"molecules_processed"} | {f"count_above_{threshold:g}" for threshold in THRESHOLDS}
    missing_columns = required_columns - set(scores.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {sorted(missing_columns)}")

    colors = {
        0.5: "#3498db",
        0.6: "#2ecc71",
        0.7: "#e67e22",
        0.8: "#e74c3c",
    }
    x = [0, *scores["molecules_processed"].tolist()]

    fig, ax = plt.subplots(figsize=(12, 6), dpi=200)
    for threshold in THRESHOLDS:
        column = f"count_above_{threshold:g}"
        ax.plot(
            x,
            [0, *scores[column].tolist()],
            color=colors[threshold],
            linewidth=1.6,
            label=rf"Boltz score $\geq$ {threshold:g}",
        )
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Molecules processed", fontsize=13)
    ax.set_ylabel("Number of compounds above threshold", fontsize=13)
    ax.legend(frameon=False, fontsize=11, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUTPUT_PREFIX.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(OUTPUT_PREFIX.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
