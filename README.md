# BioSmart

Monorepo for CGFlow molecular optimization, the CGFlow GUI (Electron + web), and FlashBind integration.

## CGFlow setup

CGFlow lives in `cgflow/` as a git submodule ([sheepyrad/cgflow](https://github.com/sheepyrad/cgflow.git)), on branch `feat/flashbind-integration` (Boltz + FlashBind backends).

```bash
git submodule update --init --recursive
cd cgflow

mamba create -n cgflow python=3.11
mamba activate cgflow
pip install -e .
pip install -e '.[unidock]'
pip install -e '.[extra]'
pip install 'boltz[cuda]' -U
```

Prepare data, environment files, and pretrained CGFlow pose weights per `cgflow/README.md` and `cgflow/experiments/README.md`.

### FlashBind / FABind+ weights (required for FlashBind opt)

Large checkpoints are **not** in git. Download from Hugging Face after install:

```bash
# from repo root
./scripts/setup-cgflow-assets.sh

# or from cgflow/
cd cgflow && ./scripts/setup/download_flashbind_assets.sh
```

This fetches:

| Asset | Hugging Face | Local path |
|-------|--------------|------------|
| FABind+ | [KyGao/FABind_plus_model](https://huggingface.co/KyGao/FABind_plus_model) | `cgflow/src/FlashBind/FABind_plus/ckpt/` |
| FlashBind heads | [clorf6/FlashBind](https://huggingface.co/clorf6/FlashBind) | `cgflow/src/FlashBind/checkpoints/` |

FABind+ docking also needs the `fabind` conda env (`cgflow/src/FlashBind/FABind_plus/README.md`). FlashBind scoring uses `flashaffinity` (`cgflow/src/FlashBind/env.yaml`).

### Boltz optimization (NS5 example)

```bash
cd cgflow
python scripts/opt/opt_boltz.py --config ./configs/opt/NS5_crop_boltz_32_2000.yaml
```

### FlashBind optimization (NS5 example)

```bash
cd cgflow
python scripts/opt/opt_flashbind.py --config ./configs/opt/NS5_crop_flashbind_32_2000.yaml
```

## CGFlow GUI (local Electron)

```bash
cd cgflow-gui
bun install
bun run electron:dev
```

The GUI expects CGFlow at `../cgflow` and uses the `cgflow` conda environment by default. Override with `CGFLOW_CONDA_ENV` if needed.

See `cgflow-gui/README.md` and `cgflow-gui/CGFLOW_GUI.md` for architecture and development notes.

## Clone with submodules

```bash
git clone --recurse-submodules <repo-url>
# or after clone:
git submodule update --init --recursive
./scripts/setup-cgflow-assets.sh
```
