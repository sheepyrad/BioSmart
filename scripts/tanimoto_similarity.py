#!/usr/bin/env python
"""
Calculate pairwise Tanimoto similarity for molecules and plot similarity matrix.
"""

import argparse
import numpy as np
import matplotlib.pyplot as plt
from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs
from pathlib import Path


def read_smiles(filepath: str) -> list[str]:
    """Read SMILES strings from a file, one per line."""
    smiles_list = []
    with open(filepath, 'r') as f:
        for line in f:
            smiles = line.strip()
            if smiles:
                smiles_list.append(smiles)
    return smiles_list


def compute_fingerprints(smiles_list: list[str], radius: int = 2, n_bits: int = 2048):
    """Compute Morgan fingerprints for a list of SMILES."""
    fingerprints = []
    valid_indices = []
    
    for i, smiles in enumerate(smiles_list):
        mol = Chem.MolFromSmiles(smiles)
        if mol is not None:
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius, nBits=n_bits)
            fingerprints.append(fp)
            valid_indices.append(i)
        else:
            print(f"Warning: Could not parse SMILES at index {i}: {smiles}")
    
    return fingerprints, valid_indices


def compute_tanimoto_matrix(fingerprints: list) -> np.ndarray:
    """Compute pairwise Tanimoto similarity matrix."""
    n = len(fingerprints)
    similarity_matrix = np.zeros((n, n))
    
    for i in range(n):
        for j in range(n):
            similarity_matrix[i, j] = DataStructs.TanimotoSimilarity(
                fingerprints[i], fingerprints[j]
            )
    
    return similarity_matrix


def plot_similarity_matrix(
    similarity_matrix: np.ndarray,
    labels: list[str] = None,
    output_path: str = None,
    title: str = "Pairwise Tanimoto Similarity Matrix",
    figsize: tuple = (12, 10),
    cmap: str = "RdYlBu_r"
):
    """Plot the similarity matrix as a heatmap."""
    n = similarity_matrix.shape[0]
    
    fig, ax = plt.subplots(figsize=figsize)
    
    # Create heatmap
    im = ax.imshow(similarity_matrix, cmap=cmap, vmin=0, vmax=1)
    
    # Add colorbar
    cbar = ax.figure.colorbar(im, ax=ax, shrink=0.8)
    cbar.ax.set_ylabel("Tanimoto Similarity", rotation=-90, va="bottom", fontsize=12)
    
    # Set ticks and labels
    ax.set_xticks(np.arange(n))
    ax.set_yticks(np.arange(n))
    
    if labels:
        # Truncate long labels
        short_labels = [f"Mol {i+1}" for i in range(n)]
        ax.set_xticklabels(short_labels, rotation=45, ha="right", fontsize=10)
        ax.set_yticklabels(short_labels, fontsize=10)
    else:
        ax.set_xticklabels([f"Mol {i+1}" for i in range(n)], rotation=45, ha="right", fontsize=10)
        ax.set_yticklabels([f"Mol {i+1}" for i in range(n)], fontsize=10)
    
    # Add text annotations
    for i in range(n):
        for j in range(n):
            text = ax.text(
                j, i, f"{similarity_matrix[i, j]:.2f}",
                ha="center", va="center",
                color="white" if similarity_matrix[i, j] > 0.5 else "black",
                fontsize=8
            )
    
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel("Molecules", fontsize=12)
    ax.set_ylabel("Molecules", fontsize=12)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {output_path}")
    
    plt.show()
    
    return fig


def print_statistics(similarity_matrix: np.ndarray):
    """Print statistics about the similarity matrix."""
    n = similarity_matrix.shape[0]
    
    # Get upper triangle (excluding diagonal)
    upper_tri = similarity_matrix[np.triu_indices(n, k=1)]
    
    print("\n" + "="*50)
    print("Tanimoto Similarity Statistics")
    print("="*50)
    print(f"Number of molecules: {n}")
    print(f"Number of pairwise comparisons: {len(upper_tri)}")
    print(f"Mean similarity: {np.mean(upper_tri):.4f}")
    print(f"Median similarity: {np.median(upper_tri):.4f}")
    print(f"Min similarity: {np.min(upper_tri):.4f}")
    print(f"Max similarity: {np.max(upper_tri):.4f}")
    print(f"Std deviation: {np.std(upper_tri):.4f}")
    print("="*50)
    
    # Find most similar pairs (excluding self-similarity)
    print("\nTop 5 most similar pairs:")
    indices = np.argsort(upper_tri)[::-1][:5]
    pairs = list(zip(*np.triu_indices(n, k=1)))
    for idx in indices:
        i, j = pairs[idx]
        print(f"  Mol {i+1} - Mol {j+1}: {upper_tri[idx]:.4f}")
    
    # Find least similar pairs
    print("\nTop 5 least similar pairs:")
    indices = np.argsort(upper_tri)[:5]
    for idx in indices:
        i, j = pairs[idx]
        print(f"  Mol {i+1} - Mol {j+1}: {upper_tri[idx]:.4f}")


def main():
    parser = argparse.ArgumentParser(
        description="Calculate pairwise Tanimoto similarity for molecules."
    )
    parser.add_argument(
        "input_file",
        type=str,
        help="Path to file containing SMILES strings (one per line)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output path for the plot (e.g., similarity_matrix.png)"
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=2,
        help="Morgan fingerprint radius (default: 2)"
    )
    parser.add_argument(
        "--nbits",
        type=int,
        default=2048,
        help="Number of bits for fingerprint (default: 2048)"
    )
    parser.add_argument(
        "--save-csv",
        type=str,
        default=None,
        help="Save similarity matrix to CSV file"
    )
    
    args = parser.parse_args()
    
    # Read SMILES
    print(f"Reading SMILES from: {args.input_file}")
    smiles_list = read_smiles(args.input_file)
    print(f"Found {len(smiles_list)} SMILES strings")
    
    # Compute fingerprints
    print(f"Computing Morgan fingerprints (radius={args.radius}, nbits={args.nbits})...")
    fingerprints, valid_indices = compute_fingerprints(
        smiles_list, radius=args.radius, n_bits=args.nbits
    )
    print(f"Successfully computed {len(fingerprints)} fingerprints")
    
    # Compute similarity matrix
    print("Computing pairwise Tanimoto similarity...")
    similarity_matrix = compute_tanimoto_matrix(fingerprints)
    
    # Print statistics
    print_statistics(similarity_matrix)
    
    # Save to CSV if requested
    if args.save_csv:
        np.savetxt(args.save_csv, similarity_matrix, delimiter=',', fmt='%.4f')
        print(f"\nSimilarity matrix saved to: {args.save_csv}")
    
    # Plot similarity matrix
    output_path = args.output
    if output_path is None:
        # Default output path based on input file
        input_stem = Path(args.input_file).stem
        output_path = f"{input_stem}_tanimoto_matrix.png"
    
    plot_similarity_matrix(
        similarity_matrix,
        labels=[f"Mol {i+1}" for i in range(len(fingerprints))],
        output_path=output_path,
        title=f"Pairwise Tanimoto Similarity ({len(fingerprints)} molecules)"
    )


if __name__ == "__main__":
    main()
