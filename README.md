# BioSmart / Drug Pipeline

Monorepo for CGFlow molecular optimization, the CGFlow GUI (Electron + web), and FlashBind integration.

## CGFlow setup

CGFlow lives in `cgflow/` as a git submodule ([sheepyrad/cgflow](https://github.com/sheepyrad/cgflow.git)), pinned to a branch that includes Boltz and FlashBind backends.

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

Prepare data, environment files, and pretrained weights per `cgflow/README.md` and `cgflow/experiments/README.md`.

### Boltz optimization (NS5 example)

```bash
python scripts/opt/opt_boltz.py --config ./configs/opt/NS5_crop_boltz_32_2000.yaml
```

### FlashBind optimization (NS5 example)

```bash
python scripts/opt/opt_flashbind.py --config ./configs/opt/NS5_crop_flashbind_32_2000.yaml
```

FlashBind expects the `flashaffinity` conda env and FABind+ checkpoints under `src/FlashBind/` (see config YAML).

## CGFlow GUI (local Electron)

```bash
cd cgflow-gui
bun install
bun run electron:dev
```

The GUI expects CGFlow at `../cgflow` and uses the `cgflow` conda environment by default. Override with `CGFLOW_CONDA_ENV` if needed.

See `cgflow-gui/README.md` and `cgflow-gui/CGFLOW_GUI.md` for architecture and development notes.

## Submodule note

After cloning, initialize the submodule:

```bash
git clone --recurse-submodules <repo-url>
# or
git submodule update --init --recursive
```

The `cgflow` submodule should track `feat/flashbind-integration` (or `main` once merged upstream) for FlashBind + drug-pipeline integration.
