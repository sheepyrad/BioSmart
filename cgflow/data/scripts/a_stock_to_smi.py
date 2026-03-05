import argparse
import multiprocessing
import os
from pathlib import Path

from a_refine_smi import get_clean_smiles
from rdkit import Chem
from tqdm import tqdm


def main(block_path: str, save_block_path: str, num_cpus: int):
    block_file = Path(block_path)
    assert block_file.suffix == ".sdf"

    print("Read SDF Files")
    mols = list(Chem.SDMolSupplier(str(block_file)))
    mols = [mol for mol in mols if mol is not None]
    id_keys = ("Catalog_ID", "ID", "_Name")
    ids = []
    missing_id_count = 0
    for i, mol in enumerate(mols):
        mol_id = next((mol.GetProp(key) for key in id_keys if mol.HasProp(key)), None)
        if not mol_id:
            mol_id = f"MOL_{i}"
            missing_id_count += 1
        ids.append(mol_id)

    if missing_id_count:
        print(f"Warning: {missing_id_count} molecules missing ID fields {id_keys}. Using generated IDs.")
    print("Including Mols:", len(mols))
    print("Run Building Blocks...")
    clean_smiles_list = []
    for idx in tqdm(range(0, len(mols), 10000)):
        chunk = [Chem.MolToSmiles(mol) for mol in mols[idx : idx + 10000]]
        with multiprocessing.Pool(num_cpus) as pool:
            results = pool.map(get_clean_smiles, chunk)
        clean_smiles_list.extend(results)

    with open(save_block_path, "w") as w:
        for smiles, id in zip(clean_smiles_list, ids, strict=True):
            if smiles is not None:
                w.write(f"{smiles}\t{id}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get clean building blocks")
    parser.add_argument(
        "-b", "--building_block_path", type=str, help="Path to input enamine building block file (.sdf)", required=True
    )
    parser.add_argument(
        "-o",
        "--out_path",
        type=str,
        help="Path to output smiles file",
        default="./building_blocks/enamine_stock.smi",
    )
    parser.add_argument("--cpu", type=int, help="Num Workers", default=len(os.sched_getaffinity(0)))
    args = parser.parse_args()

    main(args.building_block_path, args.out_path, args.cpu)
