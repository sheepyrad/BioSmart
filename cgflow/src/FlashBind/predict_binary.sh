#!/bin/bash

CHECKPOINTS=(
    "./checkpoints/binary_1.ckpt"
    "./checkpoints/binary_2.ckpt"
)

torchrun --nproc_per_node=1 --rdzv_endpoint="localhost:29546" ./scripts/predict.py \
--data /media/backup/p2-conrad/mf-pcba/subset_id.json \
--structure /media/backup/p2-conrad/mf-pcba/pdb \
--structure_type pdb \
--ligand /media/backup/p2-conrad/mf-pcba/ligand_sdf.lmdb \
--ligand_type sdf \
--pocket_indices /media/backup/p2-conrad/mf-pcba/pocket_indices.lmdb \
--protein_repr /media/backup/p2-conrad/mf-pcba/repr/esm3.pt \
--ligand_repr /media/backup/p2-conrad/mf-pcba/repr/torchdrug.lmdb \
--distance_threshold 20.0 \
--out_dir /media/backup/p2-conrad/flashaffinity/binary \
--devices 1 \
--affinity_checkpoint "${CHECKPOINTS[@]}"
