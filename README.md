# BioSmart

Monorepo for CGFlow molecular optimization, the CGFlow GUI (Electron + web), and FlashBind integration.

## Install

CGFlow is part of this repo. One `pixi.lock` defines four environments that are solved separately:

| Environment | Role | Torch wheel index |
|-------------|------|-------------------|
| `default` | CGFlow + Boltz-2 | `cu124`, torch `2.6.0+cu124` |
| `server` | torch-free API runtime | none |
| `fabind` | FABind+ | `cu113`, torch `1.12.0+cu113` |
| `flashaffinity` | FlashBind | `cu126`, torch `2.7.1+cu126` |

`server`, `fabind`, and `flashaffinity` set `no-default-feature` and do not share a solve-group with `default`. On Ubuntu 20.04 (glibc 2.31) the CGFlow stack stays on torch `2.6.0+cu124`. PyG wheels for torch 2.9.x+cu126 need glibc 2.32+.

```bash
pixi install
```

Pose weights under `cgflow/weights/` are not in git. See `cgflow/README.md`.

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

FABind+ runs in the `fabind` pixi environment. FlashBind scoring runs in `flashaffinity`.

### Boltz optimization (NS5 example)

The checked-in config is a 2000×32 budget. A headless check of the same entry point uses one Iteration and one Candidate, and points `--env_dir` at a Building-block library (not shipped in the repo):

```bash
pixi run -e default -- python cgflow/scripts/opt/opt_boltz.py \
  --config cgflow/configs/opt/NS5_crop_boltz_32_2000.yaml \
  --env_dir /path/to/library \
  --num_steps 1 \
  --num_sampling_per_step 1 \
  --result_dir /path/to/run
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

## Clone

```bash
git clone <repo-url>
pixi install
./scripts/setup-cgflow-assets.sh
```
