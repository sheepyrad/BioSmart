# FABind Plus Model Checkpoint

`fabind_plus_best_ckpt.bin` — regression-based FABind+.

`confidence_model.bin` — sampling-based FABind+.

These files are **not** stored in git. Download them after cloning:

```bash
# from cgflow repo root
./scripts/setup/download_flashbind_assets.sh --fabind-only
```

Source: [KyGao/FABind_plus_model](https://huggingface.co/KyGao/FABind_plus_model) on Hugging Face.

Alternative (upstream FABind repo with git-lfs):

```bash
git lfs install
git clone https://github.com/QizhiPei/FABind.git --recursive /tmp/FABind
cp /tmp/FABind/FABind_plus/ckpt/*.bin .
```
