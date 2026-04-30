"""Print the average pairwise Tanimoto similarity for Supplementary Data S1."""

from pathlib import Path

import pandas as pd


DATA_PATH = Path(__file__).resolve().parent / "top100_boltz_unique_pairwise_tanimoto.csv"
TANIMOTO_COLUMN = "tanimoto_similarity"


def main() -> None:
    pairwise = pd.read_csv(DATA_PATH)
    if TANIMOTO_COLUMN not in pairwise.columns:
        raise ValueError(f"Missing required column: {TANIMOTO_COLUMN}")

    average_tanimoto = pairwise[TANIMOTO_COLUMN].mean()
    print(f"Pairwise comparisons: {len(pairwise)}")
    print(f"Average pairwise Tanimoto similarity: {average_tanimoto:.6f}")


if __name__ == "__main__":
    main()
