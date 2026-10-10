# Running the full pipeline on a GPU

Start to finish, for someone with a GPU and their own enzyme. No cluster
needed — every command here runs on one machine.

If you only want to *measure* tunnels and not redesign anything, you do not
need any of this: see [the measurement-only path](#measurement-only-no-gpu) at
the bottom.

**Time:** about an hour of setup, most of it downloading model weights. The run
itself depends on your card and how many designs you ask for.

---

## 1. Install

```bash
git clone https://gitlab.igem.org/2026/software/dtu-denmark/channel-design.git
cd channel-design
```

Everything below needs **Python 3.10 or newer**. The conda environments pin
their own interpreter, so this only matters if you run the test suite against
a system Python first.

Two environments, because they conflict — the design stack needs torch, the
measurement stack pins `numpy<2.0` for the RDKit and Vina ABI.

**The design environment:**

```bash
conda create -n protein-design python=3.11 -y
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
