---
status: accepted
date: 2026-09-16
---

# Hybrid storage: engine-owned Run database per Run folder, rebuildable central Index

Candidate data (SMILES, scores, routes, artifact locations) is written by the engine into one SQLite Run database inside each Run folder; this is the source of truth and the unit of portability. The server maintains a central Index in its registry (SQLite, WAL) populated idempotently from events, holding per-Candidate descriptors, fingerprints and best scores across all Runs for search and comparison. The Index is derived and can always be rebuilt by importing Run folders.

## Considered options

- Per-Run databases only: cross-Run search ("have I seen this SMILES", compare Runs) would require attaching many files.
- One central database only: headless Runs would be unqueryable without the server, and a Run folder would not be interpretable on its own.
- Postgres: unnecessary for a single-node solo workstation; adds a second container.

## Consequences

- Routes are stored as a JSON blob per Candidate in v1; relational route analytics can be added in the Index later.
- Descriptors (MW, logP, QED, SA, fingerprints, filters) are computed once by the server at ingest, not by the engine.
- Scorer working files stay on disk under the Run folder (retained in full; dedup of per-Candidate Target/MSA processing to be verified later); the Runs root is user-configurable and may be a network drive.
- Failed and filtered Candidates are stored with a status and reason.
- A one-off importer for legacy Boltz-2 result folders is planned (low priority).
