"""``biosmart run`` command."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from biosmart.engine import execute_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biosmart")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run_parser = subcommands.add_parser("run", help="Run one optimisation with the given spec")
    run_parser.add_argument("spec", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args.spec)
    return 2


def _run(spec_path: Path) -> int:
    runs_root_env = os.environ.get("BIOSMART_RUNS_ROOT")
    if not runs_root_env:
        print("BIOSMART_RUNS_ROOT is required", file=sys.stderr)
        return 2
    runs_root = Path(runs_root_env)
    registry_env = os.environ.get("BIOSMART_REGISTRY")
    registry = Path(registry_env) if registry_env else runs_root / "registry.sqlite"
    try:
        folder = execute_run(spec_path, runs_root, registry)
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
