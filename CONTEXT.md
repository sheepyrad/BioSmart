# BioSmart

BioSmart designs synthesisable drug candidates for a protein target by training the CGFlow generative policy against a frozen structure-based scorer. This glossary fixes the words used in the UI, docs, API and code.

## Language

### The optimisation loop

**Run**:
One optimisation job against one Target with one Scorer, one Building-block library and one Budget.
_Avoid_: training, experiment, opt, campaign, job

**Target**:
The protein structure (PDB) candidates are designed against.
_Avoid_: protein, receptor, system

**Pocket**:
The binding site on a Target, defined by selected residues or by a reference ligand.
_Avoid_: binding site, box, center/size

**Scorer**:
A frozen model that scores Candidates against the Target. BioSmart ships Boltz-2 and FlashBind.
_Avoid_: oracle, engine, reward function, task, backend

**Scoring round**:
One batch of Candidates sent to the Scorer together.
_Avoid_: oracle index, oracle round, batch

**Iteration**:
One update step of the CGFlow policy.
_Avoid_: step, training step, epoch

**Budget**:
How much a Run may spend: Iterations × Candidates per Iteration.
_Avoid_: num_steps, num_sampling_per_step, oracle budget

**Candidate**:
A generated molecule together with its synthesis route and predicted 3D pose.
_Avoid_: molecule, sample, generated object, ligand

**Building-block library**:
The set of purchasable fragments and reactions the policy may compose, built in-app from a supplier file (Enamine Catalog, Enamine Stock, or a plain SMILES list) and stamped with its creation date. Several may coexist; a Run records which one it used.
_Avoid_: env, env_dir, environment, generative environment

**Library source**:
The kind of file a Building-block library was built from: Enamine Catalog, Enamine Stock, or SMILES list. Determines the extraction procedure.
_Avoid_: stock/catalog used interchangeably

**Preset**:
A named Budget (Quick, Standard, Thorough). Its time estimate is derived from observed Scoring-round durations, not fixed numbers.
_Avoid_: profile, mode

**Paused**:
Run state after Stop: policy checkpoint and Scorer cache are flushed and the Run can be Resumed. Applies to every Scorer.
_Avoid_: stopped, killed, interrupted

**Reference ligand**:
A ligand structure placed in the Pocket, used to derive the Pocket for the FlashBind Scorer. Boltz-2 uses selected residues instead.
_Avoid_: ref_ligand, crystal ligand

### Storage

**Run folder**:
The self-contained directory holding everything about one Run: spec, manifest, events, the Run database, checkpoints, poses, Scorer working files, and copies of the Target, Pocket and Library metadata. The unit of portability, import and archive.
_Avoid_: result_dir, log_dir, output folder

**Runs root**:
The user-configured directory under which Run folders are created. May be a network drive.
_Avoid_: result_dir, data dir

**Run database**:
The SQLite file inside a Run folder, written by the engine, holding Candidates, scores, Scoring rounds, Iterations and artifact locations for that Run only.
_Avoid_: generated_objs, scores db, sqlite log

**Index**:
The central, rebuildable table set in the registry that summarises Candidates across all Runs for search, comparison and descriptors. Derived from Run databases; never the source of truth.
_Avoid_: central DB, cache

**Registry**:
The server's SQLite database of Runs, Libraries, Targets, queue and settings.
_Avoid_: app DB, runs.json

**Scorer cache**:
Scores reusable across Runs, keyed by Scorer, Scorer version, scoring context (Target, Pocket, MSA) and canonical SMILES.
_Avoid_: reward cache

**Provenance**:
The recorded facts needed to reproduce or defend a Run's numbers: spec, Library and Target hashes, model versions, commands, seed, hardware.
_Avoid_: metadata, config dump

### Models

**CGFlow**:
The generative method (policy + pose model) that BioSmart trains. Not a Scorer.
_Avoid_: the model, synthflow, rxnflow

**Pose model**:
The pretrained CGFlow component that predicts a Candidate's 3D pose in the Pocket.
_Avoid_: checkpoint, ckpt, semlaflow

**Boltz-2**:
Co-folding Scorer; predicts the Target–Candidate complex and an affinity.
_Avoid_: boltz, cofold

**FlashBind**:
Affinity Scorer that scores a docked pose; obtains poses from FABind+.
_Avoid_: flashaffinity

**FABind+**:
Docking model used only to produce poses for the FlashBind Scorer. Not user-selectable.
_Avoid_: fabind

**Pose provider**:
The component a Scorer uses to obtain a Candidate's 3D pose before scoring. FlashBind's default is FABind+; the CGFlow Pose model is a possible alternative.
_Avoid_: docker, docking backend

**Scorer worker**:
A long-lived process, one per Python environment, that loads a Scorer's or Pose provider's models once at Run start and scores Candidates on request until the Run ends.
_Avoid_: subprocess, conda run, predict script
