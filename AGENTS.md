## Learned User Preferences

- Run FABind_plus (FABind) Python entry points in the conda environment named `fabind`, not only the main project env.
- On this machine, keep Hugging Face Hub model caches on the larger disk at `/media/data/conrad_hku/hf_cache` (use `flashbind.hf_hub_cache` / `HF_HUB_CACHE` where the pipeline supports it).
- For cgflow-gui, prefer ECharts via `echarts-for-react` over Plotly for charts and dashboards.
- For cgflow-gui web mode, type absolute file paths for inputs and outputs; do not rely on client-side file pickers for server-side paths.
- Prefer cgflow-gui config layout as a single column (Input PDB → Target residues → Opt params → Directories) for responsive scaling.

## Learned Workspace Facts

- `cgflow/` is files in the tree, not a git submodule.
- Install with pixi from the repo root. One `pixi.lock` defines four environments: `server` (torch-free), `default` (CGFlow + Boltz-2), `fabind`, and `flashaffinity`.
- Start the desktop GUI from `cgflow-gui/` with `bun run electron:dev`; start web mode with `bun run dev:web` (expects `../cgflow`).
- Scripts that still call `synthflow.utils.conda_env.run_in_conda_env` use the `fabind` conda env for those subprocesses. FlashBind optimization invokes FABind_plus that way.
- FABind+ and FlashBind `.ckpt`/`.bin` weights are not in git; run `./scripts/setup-cgflow-assets.sh` (or `cgflow/scripts/setup/download_flashbind_assets.sh`).
- The FlashBind task supports `hf_hub_cache` so representation subprocesses (e.g. ESM3 downloads) can set `HF_HUB_CACHE` to a large-disk path.
- On Ubuntu 20.04 (glibc 2.31), the CGFlow stack uses `torch==2.6.0+cu124` and PyG wheels from `torch-2.6.0+cu124.html`. The `flashaffinity` env pins torch `2.7.1+cu126`; its `torch_scatter` wheel does not import on glibc 2.31.
- Install cgflow editable from `cgflow/` (`pip install -e .` inside that directory, or the pixi `default` env) so `src/` packages such as `rxnflow` resolve in scripts.
- When installing `boltz[cuda]`, pin torch with a constraints file (see root `README.md`) so pip does not upgrade the PyTorch stack.
- On this machine, miniforge/conda envs and large artifacts live under `/media/data/conrad_hku/` (`miniforge3`, `cgflow_env`, `cgflow_web/result`, `hf_cache`).
- CGFlow runner write allowlist: set `CGFLOW_ALLOWED_WORKSPACE_PATHS` in `cgflow-gui/.env.local` for writable `/media/data/conrad_hku/...` paths (evaluated lazily after `.env.local` loads).

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `sheepyrad/BioSmart` (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.

