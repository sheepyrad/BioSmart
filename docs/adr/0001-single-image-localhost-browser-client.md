---
status: accepted
date: 2026-09-16
---

# Ship BioSmart as one container image with a localhost browser client; remove Electron

BioSmart needs three mutually incompatible Python/CUDA stacks (cgflow+Boltz-2, flashaffinity, fabind) and several gigabytes of weights, and its target deployment is a scientist's own Linux GPU workstation. We ship a single container image (built from one `pixi.lock`, so a host-native pixi install is possible as a fallback) containing all environments and a FastAPI server that serves the web UI on `127.0.0.1` only. Electron, Bun and the Node runner are removed: the desktop shell never solved a real problem because the compute had to be on the same Linux box anyway, and it made packaging impossible.

## Considered options

- Fix Electron packaging (`extraResources`, bundled conda): still requires host conda/CUDA management and multiplies installer variants.
- Docker only, no host-native path: rejected because some sites cannot run a Docker daemon; pixi from the same lockfile covers them.
- LAN-exposed shared server with tokens: rejected for v1. Solo workstation is the sole v1 topology. v2 remote access is the tailnet address in [ADR 0006](0006-v2-host-worker-tailnet-ui.md), not binding `0.0.0.0`.

## Consequences

- Host prerequisites collapse to Linux + NVIDIA driver + Docker (installer can install the latter two on Ubuntu).
- Image is large (≈20 GB); accepted as a one-time cost.
- Multi-user and remote access are out of scope for v1. v2 host/worker installs and a tailnet UI are [ADR 0006](0006-v2-host-worker-tailnet-ui.md). This decision remains the v1 topology.
