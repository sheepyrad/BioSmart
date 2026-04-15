## Learned User Preferences

- Run FABind_plus (FABind) Python entry points in the conda environment named `fabind`, not only the main project env.
- On this machine, keep Hugging Face Hub model caches on the larger disk at `/media/data/conrad_hku/hf_cache` (use `flashbind.hf_hub_cache` / `HF_HUB_CACHE` where the pipeline supports it).
- For cgflow-gui, prefer ECharts via `echarts-for-react` over Plotly for charts and dashboards.

## Learned Workspace Facts

- FlashBind optimization invokes FABind_plus scripts through `synthflow.utils.conda_env.run_in_conda_env`, using the `fabind` conda env for those subprocesses.
- The FlashBind task supports `hf_hub_cache` so representation subprocesses (e.g. ESM3 downloads) can set `HF_HUB_CACHE` to a large-disk path.
