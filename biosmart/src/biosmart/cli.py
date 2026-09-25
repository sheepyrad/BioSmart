"""``biosmart run`` and ``biosmart doctor``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from biosmart.doctor import apply_fix, examine, render, report_payload
from biosmart.engine import resume_run
from biosmart.libraries import (
    LibraryBuildError,
    build_stock_library,
    default_libraries_root,
    default_library,
    list_libraries,
)
from biosmart.scoring import ScorerFailed
from biosmart.start import StartRefused, execute_guarded
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

    library = subcommands.add_parser("library", help="Building-block libraries")
    library_sub = library.add_subparsers(dest="library_command", required=True)

    build = library_sub.add_parser("build", help="Build a library from Enamine Stock")
    build.add_argument("file", type=Path)
    build.add_argument("--source", required=True, choices=("stock", "catalog", "smiles"))
    build.add_argument("--druglike", action="store_true")
    build.add_argument("--libraries-root", type=Path, default=None)
    build.add_argument("--cpu", type=int, default=None)

    listing = library_sub.add_parser("list", help="List libraries; the newest is the default")
    listing.add_argument("--libraries-root", type=Path, default=None)

    doctor = subcommands.add_parser("doctor", help="Report whether this workstation can Start a Run")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("rest", nargs="*")

    args = parser.parse_args(argv)
    try:
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
        if args.command == "library" and args.library_command == "build":
            return _build(args)
        if args.command == "library" and args.library_command == "list":
            return _list(args)
        if args.command == "doctor":
            return _doctor(json_output=args.json, rest=args.rest)
    except LibraryBuildError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Unknown command", file=sys.stderr)
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
        folder = execute_guarded(spec_path, runs_root, registry)
    except StartRefused as exc:
        print(render(exc.report), file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
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


def _root(value: Path | None) -> Path:
    return value if value is not None else default_libraries_root()


def _build(args: argparse.Namespace) -> int:
    if args.source != "stock":
        print(
            "This command builds a Building-block library from Enamine Stock.",
            file=sys.stderr,
        )
        return 2
    library = build_stock_library(
        args.file,
        _root(args.libraries_root),
        druglike=bool(args.druglike),
        cpu=args.cpu,
    )
    print(json.dumps(library.to_dict()))
    return 0


def _list(args: argparse.Namespace) -> int:
    root = _root(args.libraries_root)
    libraries = list_libraries(root)
    chosen = default_library(root)
    default_id = chosen.id if chosen is not None else None
    print(
        json.dumps(
            {
                "default_id": default_id,
                "libraries": [library.to_dict() for library in libraries],
            }
        )
    )
    return 0


def _doctor(*, json_output: bool, rest: list[str]) -> int:
    if rest[:1] == ["fix"]:
        if len(rest) != 2:
            print("usage: biosmart doctor fix weights", file=sys.stderr)
            return 2
        try:
            report = apply_fix(rest[1])
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    elif rest:
        print(f"unknown doctor command: {' '.join(rest)}", file=sys.stderr)
        return 2
    else:
        report = examine()
    if json_output:
        print(json.dumps(report_payload(report)))
    else:
        print(render(report))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
