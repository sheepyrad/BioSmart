---
status: accepted
date: 2026-09-16
---

# Scorer results are cached globally, keyed by scoring context and canonical SMILES

A 64,000-Candidate Boltz-2 Run takes about two weeks on an RTX 3090, and successive Runs on the same Target re-score many of the same molecules. Instead of the per-Run reward cache, the engine consults a global Scorer cache keyed by `(scorer, scorer_version, context_hash, canonical_isomeric_smiles)`, where `context_hash` covers the Target file hash, the Pocket definition and the MSA hash. A hit skips docking/co-folding and reuses the stored scores and artifact reference.

## Considered options

- Per-Run cache only (status quo): no reuse across Runs.
- Cache keyed by SMILES alone: wrong, a score is meaningless outside its Target/Pocket/MSA context.

## Consequences

- Provenance must record the full scoring context (including the returned `.a3m` when the MSA server is used) so cache hits are defensible.
- Changing Scorer version or Pocket definition invalidates hits by construction; no manual cache clearing is needed.
