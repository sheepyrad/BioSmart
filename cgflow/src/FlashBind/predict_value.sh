#!/bin/bash

CHECKPOINTS=(
    "./checkpoints/value_1.ckpt"
    "./checkpoints/value_2.ckpt"
)

torchrun --nproc_per_node=1 --rdzv_endpoint="localhost:29501" ./scripts/predict.py \
--data /media/backup/p2-conrad/flashbind_data/openfe/id.json \
--task value \
--structure /media/backup/p2-conrad/flashbind_data/openfe/pdb \
--structure_type pdb \
--ligand /media/backup/p2-conrad/flashbind_data/openfe/ligand_sdf.lmdb \
--ligand_type sdf \
--protein_repr /media/backup/p2-conrad/flashbind_data/openfe/repr/esm3.lmdb \
--ligand_repr /media/backup/p2-conrad/flashbind_data/openfe/repr/torchdrug.lmdb \
--distance_threshold 20.0 \
--out_dir /media/backup/p2-conrad/flashaffinity/value/openfe \
--devices 1 \
--affinity_checkpoint "${CHECKPOINTS[@]}" \

sleep 10
pkill -f predict.py
sleep 10

torchrun --nproc_per_node=1 --rdzv_endpoint="localhost:29501" ./scripts/predict.py \
--data /media/backup/p2-conrad/flashbind_data/fep4/id.json \
--task value \
--structure /media/backup/p2-conrad/flashbind_data/fep4/pdb \
--structure_type pdb \
--ligand /media/backup/p2-conrad/flashbind_data/fep4/ligand_sdf.lmdb \
--ligand_type sdf \
--protein_repr /media/backup/p2-conrad/flashbind_data/fep4/repr/esm3.lmdb \
--ligand_repr /media/backup/p2-conrad/flashbind_data/fep4/repr/torchdrug.lmdb \
--distance_threshold 20.0 \
--out_dir /media/backup/p2-conrad/flashaffinity/value/fep4 \
--devices 1 \
--affinity_checkpoint "${CHECKPOINTS[@]}" \

sleep 10
pkill -f predict.py
sleep 10

torchrun --nproc_per_node=1 --rdzv_endpoint="localhost:29501" ./scripts/predict.py \
--data /media/backup/p2-conrad/flashbind_data/casp16/id.json \
--task value \
--structure /media/backup/p2-conrad/flashbind_data/casp16/pdb \
--structure_type pdb \
--ligand /media/backup/p2-conrad/flashbind_data/casp16/ligand_sdf.lmdb \
--ligand_type sdf \
--protein_repr /media/backup/p2-conrad/flashbind_data/casp16/repr/esm3.lmdb \
--ligand_repr /media/backup/p2-conrad/flashbind_data/casp16/repr/torchdrug.lmdb \
--distance_threshold 20.0 \
--out_dir /media/backup/p2-conrad/flashaffinity/value/casp16 \
--devices 1 \
--affinity_checkpoint "${CHECKPOINTS[@]}" \
