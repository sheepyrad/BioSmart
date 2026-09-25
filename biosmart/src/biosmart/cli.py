"""``biosmart`` command line."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from biosmart.engine import execute_run, resume_run
from biosmart.scoring import ScorerFailed
from biosmart.worker import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biosmart")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run_parser = subcommands.add_parser("run", help="Run one optimisation with the given spec")
    run_parser.add_argument("spec", nargs="?", type=Path)
    run_parser.add_argument(
        "--resume",
        type=Path,
        metavar="RUN_FOLDER",
        help="Continue a Paused Run from its Run folder",
    )
    worker_parser = subcommands.add_parser(
        "worker",
        help="Accept prepare, score, and flush from a host on the tailnet",
    )
    worker_parser.add_argument("--listen", required=True)
    worker_parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        if args.resume is not None and args.spec is not None:
            print("Resume continues a Paused Run and does not take a spec", file=sys.stderr)
            return 2
        if args.resume is not None:
            return _resume(args.resume)
        if args.spec is None:
            print("A Run spec is required", file=sys.stderr)
            return 2
        return _run(args.spec)
    if args.command == "worker":
        return _worker(args.listen, args.ready_file)
    return 2


def _workspace() -> tuple[Path, Path] | None:
    runs_root_env = os.environ.get("BIOSMART_RUNS_ROOT")
    if not runs_root_env:
        print("BIOSMART_RUNS_ROOT is required", file=sys.stderr)
        return None
    runs_root = Path(runs_root_env)
    registry_env = os.environ.get("BIOSMART_REGISTRY")
    registry = Path(registry_env) if registry_env else runs_root / "registry.sqlite"
    return runs_root, registry


def _run(spec_path: Path) -> int:
    workspace = _workspace()
    if workspace is None:
        return 2
    runs_root, registry = workspace
    try:
        folder = execute_run(spec_path, runs_root, registry)
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ScorerFailed as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(folder)
    return 0


def _resume(folder: Path) -> int:
    workspace = _workspace()
    if workspace is None:
        return 2
    runs_root, registry = workspace
    try:
        resumed = resume_run(folder, runs_root, registry)
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ScorerFailed as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(resumed)
    return 0


def _worker(listen: str, ready_file: Path | None) -> int:
    try:
        serve(listen, ready_file)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
