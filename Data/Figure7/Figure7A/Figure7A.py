"""Generate Figure 7A: top Boltz score and top-10/top-100 averages."""

from heapq import heappush, heapreplace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "Figure7_boltz_scores_cumulative_thresholds.csv"
OUTPUT_PREFIX = BASE_DIR / "Figure7A"


def calculate_running_top_scores(scores: np.ndarray) -> pd.DataFrame:
    best_scores = np.empty(len(scores), dtype=float)
    top10_average = np.empty(len(scores), dtype=float)
    top100_average = np.empty(len(scores), dtype=float)
    heap10: list[float] = []
    heap100: list[float] = []
    current_best = -np.inf

    for index, score in enumerate(scores):
        current_best = max(current_best, float(score))
        best_scores[index] = current_best

        if len(heap10) < 10:
            heappush(heap10, float(score))
        elif score > heap10[0]:
            heapreplace(heap10, float(score))
        top10_average[index] = float(np.mean(heap10))

        if len(heap100) < 100:
            heappush(heap100, float(score))
        elif score > heap100[0]:
            heapreplace(heap100, float(score))
        top100_average[index] = float(np.mean(heap100))

    return pd.DataFrame(
        {
            "molecules_processed": np.arange(1, len(scores) + 1),
            "top_score": best_scores,
            "top10_average_score": top10_average,
            "top100_average_score": top100_average,
        }
    )


def main() -> None:
    scores = pd.read_csv(DATA_PATH).sort_values("molecules_processed").reset_index(drop=True)
    if scores.empty:
        raise SystemExit(f"No data found: {DATA_PATH}")
    if "boltz_score" not in scores.columns:
        raise ValueError("Missing required column: boltz_score")

    running = calculate_running_top_scores(scores["boltz_score"].to_numpy(dtype=float))
    x = [0, *running["molecules_processed"].tolist()]

    fig, ax = plt.subplots(figsize=(12, 6), dpi=200)
    ax.plot(x, [0.0, *running["top_score"].tolist()], color="#e74c3c", linewidth=1.6, label="Top compound")
    ax.plot(
        x,
        [0.0, *running["top10_average_score"].tolist()],
        color="#2ecc71",
        linewidth=1.6,
        label="Average of top 10 compounds",
    )
    ax.plot(
        x,
        [0.0, *running["top100_average_score"].tolist()],
        color="#3498db",
        linewidth=1.6,
        label="Average of top 100 compounds",
    )
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Molecules processed", fontsize=13)
    ax.set_ylabel("Boltz score", fontsize=13)
    ax.legend(frameon=False, fontsize=11, loc="lower right")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUTPUT_PREFIX.with_suffix(".png"), bbox_inches="tight")
    fig.savefig(OUTPUT_PREFIX.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
