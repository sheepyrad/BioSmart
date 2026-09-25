"""`python -m biosmart doctor` and the Start gate."""

from __future__ import annotations

import argparse
import json
import sys

from biosmart.assets import sync_assets
from biosmart.doctor import apply_fix, discover, examine, render, report_payload
from biosmart.start import StartRefused, open_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biosmart")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Report whether this workstation can Start a Run")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("rest", nargs="*")

    assets = sub.add_parser("assets", help="Sync weights once, from the Doctor")
    assets.add_argument("action", choices=["sync"])

    sub.add_parser("start", help="Start a Run, or refuse when a blocking Doctor check fails")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _doctor(json_output=args.json, rest=args.rest)
    if args.command == "assets":
        return _sync()
    if args.command == "start":
        return _start()
    parser.error(f"unknown command {args.command}")
    return 2


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


def _sync() -> int:
    workstation = discover()
    synced = sync_assets(workstation)
    report = examine(workstation)
    if synced:
        print("Synced: " + ", ".join(synced))
    else:
        print("Weights already present.")
    print(render(report))
    return 0 if report.check("weights").ok else 1


def _start() -> int:
    try:
        context = open_run()
    except StartRefused as exc:
        print(render(exc.report))
        print(str(exc))
        return 1
    print("Start allowed. A Run uses local weights and does not fetch them.")
    print(f"BOLTZ_CACHE={context.env['BOLTZ_CACHE']}")
    print(f"HF_HUB_OFFLINE={context.env['HF_HUB_OFFLINE']}")
    return 0
