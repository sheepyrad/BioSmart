## Learned User Preferences

- When wiring generators or optimizers to this stack, keep FABind+ docking in its own module and call it from a thin wrapper around the existing task/trainer seam; avoid copying Boltz- or UniDock-specific pipeline internals line by line.
- For reinforcement or multi-objective loops that consume FlashBind outputs, treat binary probability and continuous affinity as separate signals (objectives or parsed reward channels) unless a single scalar is explicitly chosen.
- When running FABind+ scripts versus FlashBind scoring locally, use separate conda environments as named in the user’s setup: `fabind` for FABind+, `flashaffinity` for FlashBind.

## Learned Workspace Facts

- `scripts/predict.py` scores fixed 3D inputs (structures, docked ligand geometry, precomputed representations, optional pocket indices); it does not perform docking or build poses from SMILES alone.
- The standard FlashBind inference path under `src/affinity/` does not call FABind or FABind+ at runtime; offline preprocessing and docking are documented under `docs/data_process.md` and implemented in `FABind_plus/` and related scripts, with protein-structure sourcing logic in `src/affinity/data/fold.py`.
- Sample IDs are `prot_id_ligand_id`; `extract_ids` in `src/affinity/utils/utils.py` splits on the first underscore, while `FABind_plus/convert_data_to_csv.py` uses `rsplit('_', 1)` for the same fields—underscores inside `prot_id` can break key alignment between FABind+ artifacts and FlashBind unless IDs are normalized.
- Binary and value (affinity) prediction use different `--task` values and matching checkpoints in `scripts/predict.py`; obtaining both usually means two predict runs with the appropriate task and weights.
- Running `src/affinity/data/fold.py` as a script defaults to `./data/mf-pcba/prots.json`, `./data/mf-pcba/pdb`, and `./data/mf-pcba/boltz_work` for inputs, PDB output, and Boltz workdir—paths are relative to the process working directory, not necessarily the repo root. Now is changed to `/media/backup/p2-conrad/NS5`.
- Conda `env.yaml` pip installs are order-sensitive: `torch` must be installed before `flash-attn` (its setup imports torch). PyG packages with `+pt*` CUDA wheel tags need a matching `--find-links` line pointing at PyG’s wheel index for the torch/CUDA line; prebuilt PyG wheels often require host glibc ≥ 2.33.
- If `torch_geometric` loads without optional native wheels (`pyg-lib`, `torch-scatter`, etc.), it uses PyTorch fallbacks—mainly slower with small FP differences, not a different scoring definition unless an op errors for lack of a fallback.
