---
status: accepted
date: 2026-09-16
---

# The run contract is owned by Python: pydantic spec, JSONL events, Run folder

Previously the TypeScript runner re-implemented the run contract by hand: a Zod schema shadowing Python dataclasses, regexes over log lines, mtime polling for result directories and BFS over cgflow's output tree. We move the entire contract into the engine: a pydantic `RunSpec` is the single schema (JSON Schema and TypeScript types are generated from it and drift fails CI); the engine emits structured JSONL events (`run.started`, `iteration`, `round.*`, `candidate`, `checkpoint`, `run.paused|finished|failed`); and every Run writes a self-contained Run folder with `run.json` manifest. The server and CLI consume this contract; no TypeScript backend exists.

## Considered options

- Keep the Node runner and tighten the regexes: rejected; the duplication was the root cause, not the regex quality.
- Server-only ownership (engine emits nothing, server scrapes): rejected; headless CLI Runs must be interpretable without a server.

## Consequences

- `scripts/opt/opt_*.py` are replaced by `biosmart run <spec.json>`; machine plumbing (paths, env names, caches) leaves the spec and lives in server settings.
- Stop/Resume become Scorer-agnostic (checkpoint + Scorer cache flush on SIGTERM, non-interactive resume).
- `train.log` becomes human-only output.
