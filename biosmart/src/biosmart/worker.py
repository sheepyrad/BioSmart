"""Worker acceptor.

A worker accepts prepare, score, and flush and calls the Scorer seam. Each
call is one JSON object per line. It serves no UI, runs no policy, and has
no queue. It asks for no token.

On the tailnet the line is a TCP socket. Loopback is the CI stand-in for
that address. A hostname is allowed when it resolves into loopback,
Tailscale IPv4, or Tailscale IPv6. The worker does not listen on a public
LAN address.

A local Scorer worker uses the same JSON-lines on stdin and stdout. Models
stay loaded in that process until the host closes the pipe.
"""

from __future__ import annotations

import ipaddress
import json
import os
import signal
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from biosmart.scoring import Candidate, FakeScorer, ScoreResult, ScorerFailed
from biosmart.spec import PocketSpec, TargetSpec
from biosmart.storage import flush_scorer_cache

_OPS = frozenset({"prepare", "score", "flush"})
_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
_TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
