# CGFlow setup scripts

## FlashBind / FABind+ weights

Large checkpoints are fetched from Hugging Face instead of git LFS:

| Asset | Hugging Face repo | Local path |
|-------|-------------------|------------|
| FABind+ regression & sampling | [KyGao/FABind_plus_model](https://huggingface.co/KyGao/FABind_plus_model) | `src/FlashBind/FABind_plus/ckpt/` |
| FlashBind binary & value heads | [clorf6/FlashBind](https://huggingface.co/clorf6/FlashBind) | `src/FlashBind/checkpoints/` |

```bash
# from cgflow root (cgflow conda env or any Python 3.8+)
./scripts/setup/download_flashbind_assets.sh

# FABind+ only (~360 MB)
./scripts/setup/download_flashbind_assets.sh --fabind-only

# FlashBind scoring ckpts only (~250 MB for binary+value pair)
./scripts/setup/download_flashbind_assets.sh --flashbind-only
```

Requires `huggingface_hub` (installed automatically by the shell wrapper).

Optional: set `HF_HOME` or `HUGGINGFACE_HUB_CACHE` to a large disk before downloading.
