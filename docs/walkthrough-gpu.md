# Running the full pipeline on a GPU

Start to finish, for someone with a GPU and their own enzyme. No cluster
needed — every command here runs on one machine.

If you only want to *measure* tunnels and not redesign anything, you do not
need any of this: see [the measurement-only path](#measurement-only-no-gpu) at
the bottom.

**Time:** about an hour of setup, most of it downloading model weights. The run
itself depends on your card and how many designs you ask for.

## The whole thing at a glance

```
┌─ SETUP ─────────────────────────────────────────────────────────────┐
│  git clone … && cd channel-design                                   │
│  ./setup.sh --gpu                                                   │
│     ├─ uv                          installs itself if absent        │
│     ├─ Python deps from uv.lock    tests + docking + boltz + design │
│     ├─ CAVER 3.0                   downloaded, SHA-256 verified     │
│     ├─ fpocket                     built from source                │
│     └─ Java                        checked only, never installed    │
│                                                                     │
│  WEIGHTS — pick one:                                                │
│     already have them →  name them in envs/site.env, then re-run    │
│                          ./setup.sh --check  (it READS site.env, so │
│                          write it first or the report shows defaults)│
│     do not            →  ./setup.sh --gpu --weights   (tens of GB)  │
│                                                                     │
│  pip install torch --index-url …/cu128    ← YOUR CUDA, do this first│
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─ VERIFY (free, no GPU work) ────────────────────────────────────────┐
│  uv run --extra tests pytest -q      → 0 failed (1 skip is normal)  │
│  python …/site.py                    → no "DOES NOT EXIST"          │
│  python …/run_local.py --check       → GPU visible? rfd3/mpnn on    │
│                                        PATH? all 3 checkpoints?     │
│  python …/run_local.py --dry-run     → prints every command, runs   │
│                                        nothing                      │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─ PREPARE YOUR ENZYME ───────────────────────────────────────────────┐
│  cp my_enzyme.pdb enzyme_design/inputs/                             │
│     heme on its own chain; substrate on another, ~4–5 Å above the Fe │
│     ⚠ ligands MUST be HETATM, not ATOM  (see KNOWN_ISSUES.md #2)    │
│     fix_pdb_chains.py does the chain surgery                        │
│  00_make_msa.py --pdb inputs/my_enzyme.pdb   once, CPU + network    │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─ MEASURE THE PARENT  ◀── the step that makes this worth using ──────┐
│  00_caver_channel.py inputs/my_enzyme.pdb                 CPU       │
│     → baseline bottleneck radius   everything is relative to it     │
│     → FLEXIBLE_RESIDUES            chosen by geometry, not by eye   │
│  cp config_template.py config.py  →  paste the list, set the SMILES │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─ PILOT  ◀── do not skip: this is where you save a day ──────────────┐
│  run_local.py --stages prep-caver_filter      1 backbone, minutes   │
│  08_probe_channel.py <work>/diffusion_out/*.cif.gz                  │
│     on a cluster:  00_submit_all.py --pilot   same stages, via LSF  │
│                                                                     │
│          did the tunnel open?                                       │
│                │                                                    │
│      NO ───────┴──────► retune FLEXIBLE_RESIDUES or PARTIAL_T and   │
│       ▲                 repeat. If it will not open on ONE backbone │
│       └─────────────────it will not open across two hundred.        │
│                │ YES                                                │
└────────────────┼────────────────────────────────────────────────────┘
                 ▼
┌─ FULL RUN ──────────────────────────────────────────────────────────┐
│  run_local.py                        one GPU, stages run in order   │
│    0 prep → 1 rfd3 → 2 process → 3 caver_filter → 4 mpnn → 5 rf3    │
│                                     ▲                               │
│                     CPU GATE: collapsed backbones die HERE, before  │
│                     they cost GPU time in MPNN and RF3. Fails OPEN. │
│                                        → 6 score → 7 collect        │
│                                                                     │
│  on a cluster instead:  00_submit_all.py   LSF arrays, parallel     │
│      queue: --queue beats PIPELINE_QUEUE beats site.py's default    │
└──────────────────────────┬──────────────────────────────────────────┘
                           ▼
┌─ DID IT WORK? ──────────────────────────────────────────────────────┐
│  07_caver_rescore.py        rank by MEASURED Δbottleneck, never by  │
│                             how confident the model was             │
│  09_compare_to_parent.py    core survived? pinned vs flexible RMSD  │
│                             reported separately, so "fold fell      │
│                             apart" and "tunnel moved" never blur    │
│  10_plot_channels.py        profile overlay, parent vs designs      │
│  11_cluster_channels.py     cluster by channel SHAPE, not one number│
│  12_bottleneck_residues.py  what is physically blocking it — and    │
│                             was that residue even free to move?     │
└─────────────────────────────────────────────────────────────────────┘
```

Three things worth internalising before you start:

1. **`--check` before anything.** Thirty seconds, and it is the difference
   between a clean start and discovering a missing checkpoint mid-run.
2. **The pilot is the trick.** One backbone tells you whether the tunnel opens
   at all. Sequence design cannot reopen a channel diffusion closed.
3. **Stage 3 is the gate**, and it is what separates this from a plain
   RFD3 → MPNN → RF3 script: the thing being optimised is cheap to measure on
   CPU, so it is measured *before* the expensive stages rather than after.

Both drivers' pilots run the same stages — through the gate, stopping before
MPNN. That is asserted in `tests/test_stage_parity.py`, because for a while
they did not: the cluster pilot stopped one stage earlier and so could not
answer the question a pilot is for.

---

## 1. Install

```bash
git clone https://gitlab.igem.org/2026/software/dtu-denmark/channel-design.git
cd channel-design
```

Everything below needs **Python 3.12 or newer**. The conda environments pin
their own interpreter, so this only matters if you run the test suite against
a system Python first.

Two environments, because they conflict — the design stack needs torch, the
measurement stack pins `numpy<2.0` for the RDKit and Vina ABI.

**The design environment:**

```bash
conda create -n protein-design python=3.12 -y
conda activate protein-design

# Install torch for YOUR CUDA version first — check with `nvidia-smi`.
pip install torch --index-url https://download.pytorch.org/whl/cu128

pip install "rc-foundry[all]"
```

**The measurement environment:**

```bash
conda env create -f envs/docking.yml
```

**CAVER** (GPLv3, distributed from caver.cz behind a registration form, so it
cannot be fetched automatically):

```bash
./scripts/fetch_third_party.sh      # prints where to put it, then verifies
```

## 2. Get the model weights

All three models come from the same place, so this is one command:

```bash
conda activate protein-design
foundry install base-models --checkpoint-dir "$PWD/ckpt"
foundry list-installed
```

That fetches RFdiffusion3, RF3 and LigandMPNN together. `ckpt/` is gitignored.

## 3. Tell the pipeline where things are

```bash
cp envs/dtu-hpc.env.example envs/site.env
```

Edit `envs/site.env`. On a single machine most of it can stay empty — the
checkpoints default to `enzyme_design/ckpt/`, which is where step 2 put them:

```bash
export CONDA_SH=""                  # empty: the env is already active
export PROTEIN_ENV=""
export PIPELINE_WORK_ROOT="$HOME/channel-design-runs"
```

Then:

```bash
source envs/site.env
python enzyme_design/partial_diffusion/site.py
```

Every path it prints should exist. This costs nothing and catches most setup
mistakes.

## 4. Prepare your structure

Your enzyme needs: solvent stripped, heme on its own chain, substrate on
another chain roughly 4–5 Å above the iron, and — this one bites people —
**every ligand written as `HETATM`, not `ATOM`**. A substrate written as `ATOM`
is invisible to every ligand-aware step and CAVER will find no tunnel at all.

```bash
cp my_enzyme.pdb enzyme_design/inputs/
grep -E "^(ATOM|HETATM)" enzyme_design/inputs/my_enzyme.pdb | cut -c22 | sort -u
# expect three chain letters, e.g. A B C
```

`enzyme_design/partial_diffusion/scripts/fix_pdb_chains.py` does the chain
surgery if it is not already right.

## 5. Build the alignment (once per enzyme)

```bash
cd enzyme_design
python partial_diffusion/scripts/00_make_msa.py --pdb inputs/my_enzyme.pdb
```

Runs a ColabFold/MMseqs2 search and writes `my_enzyme_A.a3m.gz` beside your
structure, where the config finds it by name. Needs network, not a GPU.

RF3 can fold without an MSA, but pLDDT comes out markedly lower — if you skip
this, lower `PLDDT_CUT` to about 0.70 or the quality gate will reject almost
everything for the wrong reason.

## 6. Measure the parent enzyme

```bash
conda activate channel-design-docking     # the CAVER environment
python partial_diffusion/scripts/00_caver_channel.py inputs/my_enzyme.pdb
```

**This is the step that makes the tool worth using.** It measures your tunnel
and writes out the residues lining it, so the hardest question in this kind of
design work — *which residues should I let move?* — is answered from geometry
rather than intuition. It also records the baseline bottleneck radius that
every design will be compared against.

Keep that number. Everything downstream is relative to it.

## 7. Write your config

```bash
cp partial_diffusion/config_template.py partial_diffusion/config.py
```

Edit it — the tagged lines are the ones meant to be changed:

| set | to |
|---|---|
| `INPUT_PDB` | `inputs/my_enzyme.pdb` |
| `FLEXIBLE_RESIDUES` | the list step 6 printed |
| `SUBSTRATE_SMILES` | your substrate |
| `YOUR_NAME`, `EXPERIMENT` | anything; they name the output directory |

Everything not in `FLEXIBLE_RESIDUES` is held rigid in diffusion and native in
sequence design. That is the whole idea: change the tunnel, keep the enzyme.

`config.py` is gitignored — it is your working copy, not part of the repo.

## 8. Preflight

```bash
conda activate protein-design
python partial_diffusion/scripts/run_local.py --check
```

Verifies your GPU is visible, `rfd3` and `mpnn` are on `$PATH`, all three
checkpoints exist, the RF3 wrapper is present, and your structure and MSA
resolve. **Fix everything it reports before going further** — the alternative
is finding out several GPU-hours in.

```bash
python partial_diffusion/scripts/run_local.py --dry-run
```

Prints every command it would run, without running any of them.

## 9. Pilot first

```bash
python partial_diffusion/scripts/run_local.py --stages 0-1
python partial_diffusion/scripts/08_probe_channel.py <work>/diffusion_out/*.cif.gz
```

One pass of diffusion, then measure what came out. `08_probe_channel.py` gives
a verdict and says what to change.

**If the tunnel does not open here, it will not open across two hundred
designs.** Retune `FLEXIBLE_RESIDUES` or `PARTIAL_T` and repeat — this loop is
cheap, the full run is not.

## 10. The full run

```bash
python partial_diffusion/scripts/run_local.py
```

Seven stages in order: prep → diffusion → filter → sequence design → folding →
scoring → collect. Each one prints how long it took.

On one GPU these run sequentially. On a cluster the same work is submitted as
job arrays and the folding stage runs many designs at once, which is the whole
difference in wall time — the science is identical.

Interrupted? Resume:

```bash
python partial_diffusion/scripts/run_local.py --stages mpnn-collect
```

## 11. Did it actually work?

```bash
conda activate channel-design-docking
python partial_diffusion/scripts/07_caver_rescore.py
python partial_diffusion/scripts/09_compare_to_parent.py <work>/best_designs/*.cif
```

The first ranks designs by **measured** change in bottleneck radius — not by
how confident the model was. The second checks the fold survived, reporting
pinned and flexible regions separately so "the protein fell apart" and "the
tunnel moved" do not get confused.

## 12. Understand why

```bash
python partial_diffusion/scripts/10_plot_channels.py       # profile overlay
python partial_diffusion/scripts/11_cluster_channels.py    # cluster by shape
python partial_diffusion/scripts/12_bottleneck_residues.py # what blocks it
```

The last one is the interesting one. For our enzyme it showed the constriction
was formed by two *catalytic* residues — so the ceiling on widening was
catalytic, not geometric. That is a scientific conclusion the tool produced
rather than one we assumed.

---

## Measurement only, no GPU

If you just want to measure tunnels in your own structures — which is the part
of this most likely to be useful to someone else — you need none of the above:

```bash
conda env create -f envs/docking.yml
conda activate channel-design-docking
./scripts/fetch_third_party.sh
python enzyme_design/partial_diffusion/scripts/00_caver_channel.py my_enzyme.pdb
```

Two things this does that a plain CAVER run does not, both of which changed our
own conclusions — see [validation.md](validation.md):

1. **Strips the substrate before measuring.** A bound substrate costs about
   0.45 Å of bottleneck radius, against a 0.077 Å spread between real reference
   structures. Comparing a holo design to an apo crystal measures the substrate,
   not the protein.
2. **Stages every structure under one filename.** CAVER's tunnel search is
   randomised and seeds from the input name, so the same bytes under a
   different name give a different answer — 0.0885 Å of spread across eight
   names, against 0.0000 Å over six runs with one name.

---

## When something breaks

| symptom | look at |
|---|---|
| CAVER finds no tunnel | is your substrate `HETATM`? [KNOWN_ISSUES.md](../KNOWN_ISSUES.md#2-a-substrate-written-as-atom-is-invisible) |
| Every design is identical | `MPNN_TEMPERATURE` — the default of 0.1 is effectively argmax |
| A job says `signal 9` but the output exists | it probably succeeded; check the files before re-running |
| `--check` cannot find `rfd3` or `mpnn` | activate the design environment, or set the paths in `envs/site.env` |
| Nothing passes the quality gate | folding without an MSA? lower `PLDDT_CUT` to ~0.70 |

The full list, with the commands to verify each one, is in
[KNOWN_ISSUES.md](../KNOWN_ISSUES.md).
