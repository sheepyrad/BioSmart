---
status: accepted
date: 2026-09-16
---

# Scorers and Pose providers run as persistent per-environment workers

Today every Scoring round launches fresh processes via `conda run`: FABind+ runs three scripts, FlashBind runs `predict.py` twice, and Boltz-2 is invoked once per Candidate, so every round pays full model-load cost (Boltz-2 pays it 32 times). Inside the image the engine instead starts one long-lived Scorer worker per required environment at Run start (`/envs/<env>/bin/python`, no conda discovery), each loading its models once and serving JSON-lines requests over stdin/stdout until the Run ends. Boltz-2 becomes a resident worker that predicts Candidates in batches through Boltz's Python entry point rather than one CLI call per molecule.

## Considered options

- Keep per-round spawning, only replace `conda run` with interpreter paths: removes conda fragility but not the reload cost.
- Long-lived daemons shared across Runs: rejected for v1; per-Run workers keep GPU memory ownership simple and die with the Run.

## Consequences

- The `Scorer` / `PoseProvider` interface is the only way scoring code is invoked; the five parallel `opt_*.py` scripts disappear.
- Worker crashes are surfaced as `round.finished` events with failures, and the engine restarts the worker; Stop kills the whole process group.
- UniDock/Vina code stays in the tree for upstream parity but does not implement the interface.
