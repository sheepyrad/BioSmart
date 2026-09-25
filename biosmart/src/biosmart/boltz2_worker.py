"""Persistent Boltz-2 Scorer worker entry point.

The engine starts this with the pixi ``default`` interpreter. Requests are
JSON-lines on stdin (prepare, score, flush). Responses are JSON-lines on
stdout. Models load once inside this process. Logs stay on stderr.
"""

from __future__ import annotations

import sys


def main() -> None:
    protocol = sys.stdout
    sys.stdout = sys.stderr
    from biosmart.boltz2 import Boltz2Resident
    from biosmart.jsonl import serve

    serve(Boltz2Resident(), protocol)


if __name__ == "__main__":
    main()
