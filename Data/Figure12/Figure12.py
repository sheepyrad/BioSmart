import matplotlib.pyplot as plt
from pathlib import Path


def main() -> None:
    concentrations = [100, 50, 25, 12.5, 6.25, 3.125, 1.5625, 0.78125]
    viability_24h = [
        152.3809524,
        118.5185185,
        111.1111111,
        114.2857143,
        103.7037037,
        114.2857143,
        128,
        120,
    ]
    viability_48h = [
        145,
        112.1212121,
        110.8108108,
        100,
        97.36842105,
        108.3333333,
        111.1111111,
        92.68292683,
    ]

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.linewidth": 1.2,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig, ax = plt.subplots(figsize=(4.2, 3.2))

    ax.plot(
        concentrations,
        viability_24h,
        color="blue",
        marker="o",
        linewidth=1.8,
        markersize=5,
        markeredgewidth=0,
        label="24 h",
    )
    ax.plot(
        concentrations,
        viability_48h,
        color="red",
        marker="s",
        linewidth=1.8,
        markersize=5,
        markeredgewidth=0,
        label="48 h",
    )

    ax.set_xscale("log")
    ax.set_xticks(concentrations)
    ax.set_xticklabels(
        ["100", "50", "25", "12.5", "6.25", "3.125", "1.5625", "0.78125"],
        rotation=45,
        ha="right",
    )
    ax.set_xlabel(r"Compound 45 concentration ($\mu$M)", fontsize=10)
    ax.set_ylabel("Cell viability (%)", fontsize=10)
    y_max = max(viability_24h + viability_48h)
    ax.set_ylim(0, y_max * 1.1)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="both", which="major", direction="out", length=4, width=1.1)
    ax.tick_params(axis="both", which="minor", direction="out", length=2, width=0.8)
    ax.legend(
        frameon=False,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        handlelength=1.8,
        borderaxespad=0.0,
    )

    output_dir = Path(__file__).resolve().parent

    fig.tight_layout()
    fig.savefig(output_dir / "Figure12.png", dpi=600, bbox_inches="tight")
    fig.savefig(output_dir / "Figure12.pdf", bbox_inches="tight")
    plt.show()


if __name__ == "__main__":
    main()
