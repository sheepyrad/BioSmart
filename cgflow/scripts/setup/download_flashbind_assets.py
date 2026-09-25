#!/usr/bin/env python3
"""Download FABind+ and FlashBind checkpoints from Hugging Face (not vendored in git)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CGFLOW_ROOT = Path(__file__).resolve().parents[2]
FABIND_CKPT_DIR = CGFLOW_ROOT / "src/FlashBind/FABind_plus/ckpt"
FLASHBIND_CKPT_DIR = CGFLOW_ROOT / "src/FlashBind/checkpoints"

FABIND_REPO = "KyGao/FABind_plus_model"
FABIND_FILES = ("fabind_plus_best_ckpt.bin", "confidence_model.bin")

FLASHBIND_REPO = "clorf6/FlashBind"
FLASHBIND_FILES = ("binary_1.ckpt", "binary_2.ckpt", "value_1.ckpt", "value_2.ckpt")

MIN_BYTES = {
    "fabind_plus_best_ckpt.bin": 50_000_000,
    "confidence_model.bin": 50_000_000,
    "binary_1.ckpt": 10_000_000,
    "binary_2.ckpt": 10_000_000,
    "value_1.ckpt": 10_000_000,
    "value_2.ckpt": 10_000_000,
}


def is_lfs_pointer(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size > 512:
        return False
    try:
        return path.read_text(encoding="utf-8", errors="ignore").startswith(
            "version https://git-lfs.github.com/spec/v1"
        )
    except OSError:
        return False


def is_valid_checkpoint(path: Path, min_bytes: int) -> bool:
    if not path.is_file() or is_lfs_pointer(path):
        return False
    return path.stat().st_size >= min_bytes


def download_file(repo_id: str, filename: str, dest_dir: Path, force: bool) -> Path:
    dest = dest_dir / filename
    min_bytes = MIN_BYTES.get(filename, 1_000_000)
    if not force and is_valid_checkpoint(dest, min_bytes):
        print(f"skip (exists): {dest}")
        return dest

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub is required. Install with: pip install huggingface_hub"
        ) from exc

    dest_dir.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    print(f"download {repo_id}/{filename} -> {dest}")
    cached = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=str(dest_dir),
        local_dir_use_symlinks=False,
    )
    out = Path(cached)
    if not is_valid_checkpoint(out, min_bytes):
        raise RuntimeError(f"Downloaded file looks invalid: {out}")
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download FlashBind / FABind+ model weights from Hugging Face."
    )
    parser.add_argument(
        "--fabind-only",
        action="store_true",
        help="Only download FABind+ checkpoints (FABind_plus/ckpt/).",
    )
    parser.add_argument(
        "--flashbind-only",
        action="store_true",
        help="Only download FlashBind affinity checkpoints (src/FlashBind/checkpoints/).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if files already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.fabind_only and args.flashbind_only:
        print("Choose at most one of --fabind-only and --flashbind-only.", file=sys.stderr)
        return 2

    download_fabind = not args.flashbind_only
    download_flashbind = not args.fabind_only

    if download_fabind:
        for name in FABIND_FILES:
            download_file(FABIND_REPO, name, FABIND_CKPT_DIR, args.force)

    if download_flashbind:
        for name in FLASHBIND_FILES:
            download_file(FLASHBIND_REPO, name, FLASHBIND_CKPT_DIR, args.force)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
