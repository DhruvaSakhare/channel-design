# Partial Diffusion Pipeline — DTU iGEM BioBuilders2026

Remodel an existing UPO (or any enzyme) for a new substrate while keeping key
residues fixed. Starts from your full enzyme structure, adds controlled noise,
then denoises — producing variants that retain the overall fold but adapt the
active site.

```
Full enzyme PDB  →  RFD3 partial diffusion  →  LigandMPNN (sequences)  →  RF3 (fold & score)
```

> **Widening a substrate channel?** There is a dedicated workflow with CAVER
> measurement in the loop — a fast pilot gate, a channel-width filter between
> RFD3 and MPNN, and before/after scoring of the folded designs. Start at
> [`CHANNEL_README.md`](CHANNEL_README.md). What was tried and why it is built
> that way is in [`CHANNEL_WIDENING_LOG.md`](CHANNEL_WIDENING_LOG.md).

---

## De novo vs. partial diffusion

| | De novo (`../`) | Partial diffusion (this folder) |
|---|---|---|
| Input PDB | Small theozyme (fixed residues + ligands only) | Full enzyme structure |
| What RFD3 does | Designs a new scaffold from scratch | Remodels the existing fold |
| Use when | No starting structure | You have a good UPO fold to adapt |
| Key setting | `FREE_MIN` / `FREE_MAX` / `LENGTH` | `PARTIAL_T` |

---

## What you need before starting

1. Your full enzyme PDB in `../inputs/` with:
   - Solvent and non-essential HETATMs removed
   - Heme on its own chain (e.g. chain B)
   - Your substrate on its own chain (e.g. chain C), positioned ~4–5 Å above the iron
   - **Each ligand must be on a unique chain separate from the protein**
2. A SMILES string (or CCD code) for your substrate
3. The residue numbers of the catalytic residues coordinating the heme iron

### Preparing the PDB in PyMOL

If your PDB has all atoms on chain A, separate the ligands first:

```python
# in PyMOL
load your_enzyme.pdb
alter resn HEM, chain="B"
alter resn UNK, chain="C"   # replace UNK with your substrate residue name
alter resn UNK, resi="1"
sort
save your_enzyme_fixed.pdb
```

Verify the result — you should see exactly three chain letters:
```bash
grep -E "^(ATOM|HETATM)" your_enzyme_fixed.pdb | cut -c22 | sort -u
# expected: A  B  C
```

### Extract SMILES from your substrate PDB

If you don't have the SMILES string yet, run:
```bash
python partial_diffusion/scripts/00_smiles_from_pdb.py
```
Copy the printed SMILES into `SUBSTRATE_SMILES` in `config.py`.

### Build the MSA for your enzyme

RF3 folds every design against a multiple sequence alignment of the **native**
enzyme. Build it once per enzyme, on the login node:

```bash
python partial_diffusion/scripts/00_make_msa.py
```

This reads chain A out of `INPUT_PDB`, runs a ColabFold/MMseqs2 search, and
writes `../inputs/<pdb_stem>_A.a3m.gz`. `config.py` finds that file by name, so
**a new enzyme needs no config edit** — build the MSA and it is picked up.

It talks to `https://api.colabfold.com` over plain HTTP with no extra
dependencies, so it works on a login node with network access. Nothing to
install. If you have local ColabFold databases, `--backend local --db <dir>`
uses those instead and avoids the public server entirely.

One query per enzyme is normal, courteous use of a free shared service — don't
script it in a loop.

**If you skip this step**, RF3 folds single-sequence. That is a legitimate
choice, but pLDDT comes out markedly lower, so you must drop `PLDDT_CUT` to
around `0.70` — otherwise the gate rejects nearly every design for a reason
that has nothing to do with your designs. See
[MSA vs. single-sequence folding](#msa-vs-single-sequence-folding).

Check which mode you're in before a long run:
```bash
python -c "import partial_diffusion.config as C; print(C.NATIVE_MSA_PATH or 'SINGLE-SEQUENCE')"
```

---

## Setup (one-time, on the HPC)

**Step 1 — configure your run**

Start from the annotated template, `config_template.py` — copy it to `config.py` and edit the tagged
sections (`★ EVERY RUN`, `◆ PER EXPERIMENT`, `● PER ENZYME`, `✗ DON'T EDIT`):

```bash
cd partial_diffusion
cp config_template.py config.py
```

The key fields:

```python
YOUR_NAME         = "yourname"                 # ★ your first name, lowercase
EXPERIMENT        = "pab_upo_II_tunnel_01"      # ★ UNIQUE per run
INPUT_PDB         = "inputs/your_enzyme_fixed.pdb"  # ● prepped structure
SUBSTRATE_NAME    = "UNL"                        # ● substrate residue name in PDB
SUBSTRATE_SMILES  = "CC1CCC(...)..."             # ● substrate SMILES
PARTIAL_T         = 5                            # ◆ noise level (see tuning guide)

# ◆ THE MAIN KNOB — which residues may move (RFD3) and be redesigned (MPNN).
# Everything NOT listed is held rigid + native. CATRES and FIXED_ATOMS are
# derived from this automatically — you don't edit them by hand.
FLEXIBLE_RESIDUES = [195, 257,258,259,260,261,262, 292,295, 335,336]
```

See [Targeted remodeling](#targeted-remodeling--choosing-what-changes) below for
how `FLEXIBLE_RESIDUES` works and how to choose it.

#### Easier: pick the flexible residues visually in PyMOL

Instead of typing residue numbers into `config.py`, you can select them in PyMOL
and have the pipeline write `config.py` for you. This is the recommended way for
the team — no hand-counting residues.

**On your laptop (in PyMOL):**

1. Open your prepped structure (heme on chain B, substrate on chain C — the same
   PDB you'd feed the pipeline).
2. Select the residues you want **flexible** (free to move + redesign) and name
   the selection `flexible`. Either click residues in the GUI and rename the
   selection to `flexible`, or type e.g.:
   ```
   select flexible, chain A and resi 195+257-262+292+295+335-336
   ```
3. Load and run the helper, then call it:
   ```
   run partial_diffusion/mark_flexible.py
   mark_flexible
   ```
   (Optional args: `mark_flexible <selection>, <chain>, <out_prefix>`.)

   This writes two files: `<name>.pdb` and `<name>_flex.json` (the residue list).

**On the cluster:**

Copy those two files over, then generate the config automatically:
```bash
python partial_diffusion/scripts/00_from_pymol.py <name>.pdb <name>_flex.json \
    --experiment my_run_01 --your-name yourname \
    --substrate-name UNL --substrate-smiles "CC..."
```
This copies the PDB into `inputs/`, and writes a ready `config.py` with
`FLEXIBLE_RESIDUES` and `INPUT_PDB` filled in (`CATRES`/`FIXED_ATOMS` are derived
from them automatically). Review the file, then continue with Step 2 below.

> The PDB must already be prepped (protein on chain A, heme on B, substrate on C
> with unique atom names). `00_from_pymol.py` warns if it doesn't see those.

**Step 2 — check your PDB**

Run this before submitting any jobs — it verifies all CATRES are found, shows
ligand positions, and identifies the proximal heme coordination residue:

```bash
cd <your clone>/enzyme_design
conda activate protein-design        # see envs/design.md
python partial_diffusion/scripts/00_prep_pdb.py --check
```

---

## Running the pipeline

### Full walkthrough (start here)

Everything runs from the pipeline root on the HPC login node. The tools folder
is shared, so any team member can submit — your outputs are separated by
`YOUR_NAME` and `EXPERIMENT` in `config.py`.

**Step 1 — activate the environment (every new terminal session).**
The submit script runs `python` on the login node, so the conda environment
must be active *before* you run it. (Each LSF job it queues re-activates the
environment itself — you don't need to do anything for the jobs.)

```bash
cd <your clone>/enzyme_design
conda activate protein-design        # see envs/design.md
```

**Step 2 — edit `partial_diffusion/config.py`** with your name, experiment
name, input PDB, catalytic residues and substrate SMILES (see the
[Configuration reference](#configuration-reference) below). Set a **unique
`EXPERIMENT`** name so you don't collide with a teammate's run.

**Step 3 — sanity-check your PDB** (optional but recommended):
```bash
python partial_diffusion/scripts/00_prep_pdb.py --check
```

**Step 4 — build the MSA** (once per enzyme; skip if `../inputs/<pdb_stem>_A.a3m.gz`
already exists):
```bash
python partial_diffusion/scripts/00_make_msa.py
```
Takes a few minutes, mostly queueing on the ColabFold server. Runs on the login
node — no GPU, no job submission. `config.py` picks the file up by name, so
there is nothing to edit afterwards. See
[Build the MSA for your enzyme](#build-the-msa-for-your-enzyme) for what happens
if you skip it.

**Step 5 — submit the whole pipeline in one command:**
```bash
python partial_diffusion/scripts/00_submit_all.py
```
This queues all stages (RFD3 → MPNN → RF3 → scoring) as chained LSF jobs. Each
stage starts automatically when the previous one finishes — you don't submit
anything else by hand. It prints the job IDs and which stages were submitted vs.
skipped, e.g.:
```
[1] RFD3              submitted  job 28873xxx
[2] process+MPNN      submitted  job 28873xxx
[3] RF3 input prep    submitted  job 28873xxx
[4] RF3 array+scoring submitted  job 28873xxx
```

**Step 6 — monitor:**
```bash
bjobs            # see running/pending jobs
bstat            # summary view
```
When it's all done, your ranked designs are in
`<WORK>/best_designs/` (see [Outputs](#outputs)).

### Running several experiments at once

You can override config values on the command line — the run is frozen into a
snapshot at submission time, so editing `config.py` afterwards (or launching a
second experiment) never disturbs a run already in flight:

```bash
# baseline run
python partial_diffusion/scripts/00_submit_all.py \
    --experiment pada1_baseline \
    --partial_t 10

# more aggressive remodelling, launched right after — safe to do
python partial_diffusion/scripts/00_submit_all.py \
    --experiment pada1_aggressive \
    --partial_t 20

# helix disruption — replace blocking helix (e.g. A95-115) with shorter loop
python partial_diffusion/scripts/00_submit_all.py \
    --experiment pada1_helix_01 \
    --partial_t 15 \
    --contig "A4-94,5-12,A116-327"
```

Available flags: `--experiment`, `--partial_t`, `--contig`, `--n_batches`.
Anything not overridden comes from `config.py`.

### Re-submitting after a failure or interruption

Just run the **same** command again (same `EXPERIMENT`). Every stage checks on
the login node whether its outputs already exist and **skips submitting** the
ones that are done, so re-running is cheap and safe — it picks up from the first
incomplete stage. You'll see `SKIPPED` next to the finished stages:
```
[1] RFD3              SKIPPED (already 100 backbones)
[2] process+MPNN      SKIPPED (sequences already present)
[3] RF3 input prep    SKIPPED (inputs already built)
[4] RF3 array+scoring submitted  job 28873xxx
```

Monitor all jobs: `bstat`

---

### Manual step-by-step (for debugging)

Only needed if you want to run a single stage by hand. Run all commands from
`enzyme_design_hpc/` (the parent folder), with the conda environment active
(Step 1 above). For normal use, prefer the one-shot `00_submit_all.py`.

**Stage 0 — native MSA** (login node, no job; once per enzyme)
```bash
python partial_diffusion/scripts/00_make_msa.py
# writes ../inputs/<pdb_stem>_A.a3m.gz, picked up automatically by config.py
```

**Stage 1 — RFD3 partial diffusion**
```bash
python partial_diffusion/scripts/01_rfd3_partial_submit.py
bsub < <printed submit script path>
bstat   # wait until the job disappears
```

**Filter RFD3 outputs**
```bash
python partial_diffusion/scripts/02_rfd3_process.py
```
Filters out backbones with chain breaks or clashes. Passing backbones go to
`diffusion_out/passing/`. To inspect a backbone in PyMOL:
```bash
gunzip -k diffusion_out/passing/*.cif.gz
```

**Stage 2 — LigandMPNN (design sequences)**
```bash
python partial_diffusion/scripts/03_mpnn_submit.py
bsub < <printed submit script path>
bstat
```

**Stage 3 — RF3 (fold and score)**
```bash
python partial_diffusion/scripts/04_rf3_submit.py
bsub < <printed submit script path>
bstat
```

Monitor RF3 progress by counting score files:
```bash
ls <WORK>/rf3_out/*/*.score 2>/dev/null | wc -l
# should grow toward total number of designs
```

**Score and collect best designs**
```bash
python partial_diffusion/scripts/05_rf3_score.py
python partial_diffusion/scripts/06_collect_best.py
```

Transfer `best_designs/` to your laptop:
```bash
scp -r <WORK>/best_designs/ your_laptop:/path/to/destination/
```

---

## How skipping and chaining work (technical notes)

**Skip logic.** `00_submit_all.py` checks on the login node whether each stage's
outputs already exist. Completed GPU stages are **not submitted at all** — this
avoids a quirk of the DTU GPU queue (see below). What each stage skips on:

| Stage | Skips when |
|---|---|
| RFD3 | `diffusion_out/` has ≥ expected number of `.cif.gz` files |
| MPNN | Any `.fa` file exists under `mpnn_out/` |
| RF3 input prep | `rf3.sh` + RF3 JSON inputs already exist |
| RF3 folding | Per-task: each array task skips folds whose `out_dir` already has a CIF |
| RF3 scoring | Launcher submits scoring-only if all backbone dirs are folded; exits if `rf3_metrics.csv` exists |

**Dependencies use `ended()`, not `done()`.** On the DTU GPU queue, a job that
reserves a GPU and finishes its work quickly does not always release the node —
it can sit until wall-time and then be killed with `TERM_RUNLIMIT`. That is not
a clean exit, so a `done()` dependency would never fire and the next stage would
hang in PEND forever. `ended()` fires on *any* termination (clean or killed), and
because every stage re-checks its own outputs, the chain always advances
correctly even if an upstream job was killed at the run limit.

**Run isolation (snapshot system).** Every call to `00_submit_all.py` writes a
frozen copy of the resolved config to `<WORK>/configs/run_config.json` (and a
readable `config_used.py`). All LSF jobs for that run read their settings from
this snapshot via `PIPELINE_RUN_CONFIG`, so editing `config.py` between
submissions — e.g. to launch a second experiment — cannot corrupt a run that is
already queued or in flight.

**GPU vs CPU queues (HPC policy).** Only the three heavy stages actually use a
GPU: **RFD3**, **MPNN**, and **RF3 folding** — these go to `QUEUE` (a GPU queue).
The lightweight stages — **rf3_prep**, **rf3_launcher**, **score_stage** — are
CPU-only and go to `CPU_QUEUE`, requesting **no GPU**. This matters: a GPU is
reserved in *exclusive* mode, so sending a non-GPU job to a GPU queue blocks a
whole GPU for nothing — which HPC admins will (rightly) flag. The split is
automatic; you only need to make sure `CPU_QUEUE` in `config.py` names a real CPU
queue (check `bqueues`; on DTU it's usually `hpc`).

---

## Monitoring your jobs

Everything is done from the **login node** — you never need to `ssh` into a
compute node (that's restricted on DTU and can get you flagged).

| Command | What it tells you |
|---|---|
| `bjobs` | your jobs: which are PEND/RUN, host, time left |
| `bstat` | compact summary of all your jobs |
| `bjobs -l <id>` | full detail: **pending reason**, dependency status |
| `bjobs -p` | just the pending jobs, each with its reason |
| `bpeek <id>` | live stdout of a running job (which stage it's on) |
| `bhist -l <id>` | history of a finished job incl. **actual runtime** used |
| `tail <WORK>/logs/<name>_<id>.out` | read a job's log directly |
| `bkill <id>` / `bkill 0` | kill one job / all your jobs |

You don't need to babysit — the pipeline chains itself. Check in with `bjobs`
now and then; when `best_designs/` fills up, it's done. Avoid `watch bjobs` (it
pins your terminal); just re-run `bjobs` when you want an update.

Common pending reasons and what they mean:
- *"Host's available GPU resources cannot meet the job's requirements"* → the GPU
  queue is simply full; your job starts when a GPU frees up. Nothing is wrong.
- *"Dependency condition invalid or never satisfied"* → an upstream job was
  killed/removed. Because the pipeline uses `ended()` this should not happen; if
  it does, `bkill 0` and re-submit — finished stages are skipped automatically.

## Estimating wall times

Wall time (`-W`) is a **maximum**, not a fixed runtime — a job ends the moment
its work finishes (well before the cap) and releases the node. The defaults are
sized to the number of backbones. To tune them for your hardware, look at what a
finished job actually used:

```bash
bhist -l <jobid> | grep -iE "Dispatched|Done|Exited|CPU time"
```
The gap between *Dispatched* and *Done/Exited* is the real wall used; `CPU time`
shows whether it was working or idling. Set future walls to about that + 30%.
Shorter, accurate walls also mean that if a GPU job ever hangs, it's reaped
quickly instead of holding a GPU for hours.

---

## Troubleshooting common errors

### `ValidationError: ligand — Input should be a valid string`
RFD3 expects `ligand` as a comma-separated string, not a list. This is handled
automatically by the scripts — if you see this, make sure you're running the
scripts from this folder, not the parent pipeline's `scripts/`.

### `ValueError: Ligand chain(s) overlap with existing chain(s)`
Your ligands share a chain with the protein. Fix the PDB in PyMOL (see
"Preparing the PDB" above) — each ligand must be on its own unique chain.
The JSON must also include `"allow_ligand_on_existing_chain": true`.

### `Passing backbones: 0 / N`
All backbones failed the chain break filter. For partial diffusion this is
normal at low counts — the filter allows up to 3 chain breaks by default.
Check `scores/rfd3_metrics.csv` for the actual values.
If all designs have many chain breaks, try reducing `PARTIAL_T`.

### `Passing designs: 0 / N` at the scoring stage
Different from the above — the backbones were fine, but nothing cleared
`PLDDT_CUT` / `PAE_CUT` / `IPSAE_CUT`. Check the MSA first, before you touch the
science:
```bash
python -c "import partial_diffusion.config as C; print(C.NATIVE_MSA_PATH or 'SINGLE-SEQUENCE')"
```
If it prints `SINGLE-SEQUENCE` while `PLDDT_CUT` is 0.80+, that alone explains
it — build the MSA (`00_make_msa.py`) or lower the cut to ~0.70. Only if the MSA
was present is a zero count a real result about your `FLEXIBLE_RESIDUES` and
`PARTIAL_T`. `scores/rf3_metrics.csv` has every design's numbers, so you can see
how close they came.

### `00_make_msa.py` uses the wrong enzyme
It reads `INPUT_PDB` from `config.py`. Check the header it prints — the PDB path
and residue count must match the enzyme you mean. When running it standalone
against a non-default config, `export PIPELINE_BASE_CONFIG=partial_diffusion.<module>`
first; the script honours that variable, but only when it is exported in the
*same* shell.

### `No such file or directory: rf3_wrapper.py`
The RF3 wrapper path is wrong. In `04_rf3_submit.py`, make sure it reads:
```python
rf3_wrapper = C.LIB_ROOT / "rf3_wrapper.py"
```
not `C.PIPELINE_ROOT / "lib" / "rf3_wrapper.py"`.

### `mpnn: error: argument --fixed_residues: not allowed with argument --designed_chains`
LigandMPNN treats `--fixed_residues`, `--designed_residues`, `--fixed_chains`
and `--designed_chains` as mutually exclusive. The scripts pass only
`--fixed_residues` (comma-separated, e.g. `A72,A73,A244`). If you edit the mpnn
command, don't add a `--designed_chains` flag alongside it.

### `mpnn: ID 'A72 A73 ...' must look like '<letters><number>'`
The `--fixed_residues` value must be **comma-separated**, not space-separated —
this mpnn build splits on commas. Handled by `03_mpnn_submit.py` already.

### `json.decoder.JSONDecodeError: Expecting value: line 1 column 1`
`config.py` couldn't read `<WORK>/configs/run_config.json` — it was empty or
truncated. Re-run `00_submit_all.py` for that experiment; it rewrites the
snapshot atomically. (This can happen if a previous submit was Ctrl-C'd mid-write.)

### A job sits in RUN until wall-time / dependent jobs stay PEND
On the DTU GPU queue, a job that grabs a GPU and finishes quickly may not release
the node — it lingers until wall-time and is killed with `TERM_RUNLIMIT`. The
pipeline handles this two ways: completed stages are skipped at submission (never
launched), and dependencies use `ended()` so a run-limit kill still advances the
chain. If you ever get a genuinely stuck chain, just re-submit:
```bash
bkill 0                                        # kill your queued/stuck jobs
python partial_diffusion/scripts/00_submit_all.py   # skips finished stages, resumes
```

---

## Configuration reference

Edit **`partial_diffusion/config.py`** — the only file you need to change.

| Variable | Description |
|---|---|
| `YOUR_NAME` | Your first name, lowercase — determines your output folder |
| `EXPERIMENT` | Output folder name — **unique per run** |
| `INPUT_PDB` | Full enzyme structure (ligands on separate chains) |
| `HEME_NAME` | Heme residue name in PDB (`HEM`, `HEC`, `HEA`) |
| `SUBSTRATE_NAME` | Substrate residue name in PDB |
| `FLEXIBLE_RESIDUES` | **The main knob** — residue numbers free to move/redesign; everything else is held rigid + native (see below) |
| `_CATALYTIC_PINS` | Catalytic/structural residues → extra sidechain atoms to pin (preserves active-site geometry) |
| `CATRES` | *Derived* from `FLEXIBLE_RESIDUES` — don't edit by hand |
| `FIXED_ATOMS` | *Derived* from `FLEXIBLE_RESIDUES` + `_CATALYTIC_PINS` — don't edit by hand |
| `PARTIAL_T` | Angstroms of noise added before denoising (see tuning guide) |
| `CONTIG` | Auto = whole chain — override only for de-novo loop rebuild |
| `SUBSTRATE_SMILES` | SMILES of substrate (leave blank if using `SUBSTRATE_CCD`) |
| `SUBSTRATE_CCD` | CCD code of substrate (leave blank if using `SUBSTRATE_SMILES`) |
| `NATIVE_MSA_PATH` | MSA RF3 folds against. *Auto-discovered* as `../inputs/<pdb_stem>_A.a3m.gz` — build it with `00_make_msa.py`, don't edit. `""` = single-sequence (lower `PLDDT_CUT` to match) |
| `PLDDT_CUT` | Min enzyme pLDDT to pass (default 0.70) |
| `PAE_CUT` | Max enzyme–substrate PAE in Å to pass (default 12.0) |
| `IPSAE_CUT` | Min substrate ipSAE to pass (default 0.40) |
| `RFD3_BATCH_SIZE` | Backbones per RFD3 batch |
| `RFD3_N_BATCHES` | Batches to run — total backbones = BATCH_SIZE × N_BATCHES |
| `RF3_NUM_STEPS` | RF3 diffusion steps (50=fast, 200=production) |
| `RF3_GROUP_SIZE` | Designs per RF3 array task (default 10) |
| `QUEUE` | **GPU** queue for RFD3 / MPNN / RF3 folding (`gpua100`, `gpuv100`) |
| `CPU_QUEUE` | **CPU** queue for prep / launcher / scoring — no GPU (`hpc`) |

### Targeted remodeling — choosing what changes

The template is driven by one list, **`FLEXIBLE_RESIDUES`**. Every residue **not**
in it is held **rigid** (its backbone is pinned in RFD3) **and native** (its
sequence is kept in MPNN). Every residue **in** it is free to move and be
redesigned. `CATRES` and `FIXED_ATOMS` are built from this automatically:

```
FLEXIBLE_RESIDUES ──► RFD3 pins the backbone of everything ELSE  → only these move
                 └──► MPNN keeps the native sequence of everything ELSE → only these redesigned
```

So "keep most of the enzyme fixed, change only region X" is just: put region X's
residue numbers in `FLEXIBLE_RESIDUES`. Two things to get right:

- **Use the correct residue numbers for *your* structure.** Verify with
  `00_prep_pdb.py --check` (catalytic residues) and, ideally, a channel/pocket
  analysis (e.g. CAVER) for the residues that line the region you're targeting.
- **Keep catalytic/structural residues OUT of `FLEXIBLE_RESIDUES`** and list them
  in `_CATALYTIC_PINS` so their sidechain geometry is preserved.

Because most of the fold is frozen at the crystal structure, RF3 has little room
to get the fold wrong — this both targets your change and tends to give **higher
pLDDT** than noising the whole chain.

> **Smoke-test first.** Pinning hundreds of residues via `FIXED_ATOMS` is a heavy
> constraint; before spending GPU on 100 backbones, run one batch
> (`--n_batches 1`) and confirm RFD3 produces backbones without erroring. If it
> chokes on the large `FIXED_ATOMS`, simplify the pin atoms to `"CA"` in
> `_CATALYTIC_PINS`'s default, or reduce the pinned set.

**Method caveat:** neither RFD3 nor MPNN *optimizes* for a specific geometry
(e.g. a wide channel) — they **sample** structures/sequences near your input.
The property you want emerges and must be **selected afterwards** (e.g. filter
outputs by CAVER tunnel radius). Partial diffusion also stays close to the native
by design, so a lot of a channel's width change comes from MPNN resizing
sidechains, not from backbone motion. For large geometry changes, rebuild a loop
de-novo via `CONTIG` (next section) rather than relying on more noise.

---

### Channel-driven workflow (CAVER in the loop)

The caveat above is now implemented rather than left to you. Two scripts close
the loop around the channel, using the CAVER install in
[`../channel_discovery/`](../channel_discovery/):

```
                    ┌── 00_caver_channel.py ──┐
                    │  measure parent channel │
                    ▼                         │
 parent PDB ──► FLEXIBLE_RESIDUES             │  baseline bottleneck radius
                + channel placeholder         │  (the number to beat)
                    │                         │
                    ▼                         │
              RFD3 ─► MPNN ─► RF3 ─► 06_collect_best.py
                                              │
                                              ▼
                              07_caver_rescore.py ──► ranked by Δradius
                                                      best_designs/widened/
```

**Step 0 — measure the parent before designing anything.**

```bash
python partial_diffusion/scripts/00_caver_channel.py inputs/your_enzyme.pdb \
    --exclude 52,85,137,205,212,215,296,339      # your catalytic residues
```

This writes three files next to your input:

| File | What it is |
|---|---|
| `<stem>_flex.json` | channel-lining residues, in `mark_flexible.py`'s format |
| `<stem>_baseline.json` | the parent's bottleneck radius — the number to beat |
| `<stem>_channel.pdb` | the tunnel axis as a placeholder pseudo-ligand |

The flex JSON feeds the existing PyMOL path unchanged:

```bash
python partial_diffusion/scripts/00_from_pymol.py \
    inputs/your_enzyme.pdb inputs/your_enzyme_flex.json --experiment my_run_01
```

Why derive the list instead of writing it by hand: a hand-written
`FLEXIBLE_RESIDUES` is a homology argument ("this substitutes AaeUPO F76").
CAVER measures the channel in *your* structure. Where the two disagree, trust
the measurement — and note that CAVER reports **which tunnel** each residue
lines, so you can check you are widening *one* channel rather than six at once.

The script also splits the lining residues two ways, which tells you which lever
can move each one:

- **sidechain-lining** — MPNN can swap it for something smaller
- **backbone-only** — the wall *is* the mainchain; only RFD3 moving that
  backbone will ever open it. No amount of MPNN biasing touches these.

**The channel placeholder — the fix for "everything comes back squeezed".**

Nothing in partial diffusion rewards keeping a tunnel *open*. RFD3 packs
protein; an empty channel is a void, and compact packing wins, so free residues
collapse inward. Set in `config.py`:

```python
CHANNEL_PLACEHOLDER = "inputs/your_enzyme_channel.pdb"
```

and RFD3 gets dummy atoms along the tunnel axis as fixed ligand context — so it
packs *around* the channel instead of into it.

> **Smoke-test this one.** It passes a non-standard residue name (`TUN`) to RFD3
> as a ligand. Run `--n_batches 1` first and confirm RFD3 accepts it. If it
> rejects the residue name, set `CHANNEL_PLACEHOLDER = ""` and rely on the other
> levers.

Use `--placeholder-shrink` to place dummy atoms only where the channel is
*already* wide, which pushes RFD3 to open the narrow stretch rather than freeze
the current shape.

**Step 7 — did it actually go up?**

```bash
python partial_diffusion/scripts/07_caver_rescore.py \
    --baseline inputs/your_enzyme_baseline.json
```

Runs CAVER on every design in `best_designs/`, compares each bottleneck radius
to the parent's, writes `scores/caver_rescore.csv` ranked by Δradius, and copies
the designs that genuinely opened into `best_designs/widened/`.

This matters because `06_collect_best.py` ranks by **pLDDT**, which selects for
designs that fold *like the parent* — the opposite of what you want. A design
can pass every confidence gate and still have a channel narrower than the one
you started with. Until step 7 runs, you do not know whether the run worked.

**Two measurement rules the pipeline now enforces.** Both were found by
measuring the same structure twice and getting different answers.

*1. Always measure apo (substrate stripped).* RF3 folds enzyme + heme +
substrate, so designs arrive holo, while the CAVER reference crystals
(`5FUJ_heme`, `9HE9_heme`, `5OXU_heme`) contain only heme + metals. A bound
substrate costs ~0.4 Å of bottleneck radius — about **5x the spread between real
UPO structures** — so comparing holo designs to apo references measures ligand
occupancy, not channel shape. `00_caver_channel.py` and `07_caver_rescore.py`
both strip by default and refuse to compare a baseline measured one way against
designs measured the other. Use `--keep-substrate` on both if you deliberately
want the holo number.

> The `channel_discovery/` pipeline does **not** strip: `cif_to_pdb.py` removes
> only water, and `.pdb` inputs are copied verbatim. Any run there that compares
> designs against those references carries this artifact.

*2. Never let CAVER see the structure's real filename.* CAVER 3.0 returns a
different tunnel set for byte-identical input under a different filename — 51 vs
53 vs 55 tunnels, and 0.09 Å of spread in bottleneck radius across 8 names, again
larger than the difference between real structures. Same bytes + same name is
perfectly reproducible, so `caver_utils.run_caver` stages every structure as
`structure.pdb`. This removes the nuisance variable while leaving genuine
structural differences fully resolved. Do not "fix" this by restoring the real
name.

Measured consistently (apo, canonical staging):

| structure | bottleneck |
|---|---|
| 5FUJ (reference) | 0.975 Å |
| PabUPO-II parent | 0.983 Å |
| 9HE9 (= PabUPO-II crystal) | 1.032 Å |
| 5OXU (reference) | 1.050 Å |
| MroUPO | 1.058 Å |

**Sequence diversity.** `MPNN_TEMPERATURE` (default `0.25`) was added because
LigandMPNN's own default of `0.1` is near-deterministic: with most positions
pinned by `--fixed_residues`, the few free ones get the same amino acid nearly
every time and your N sequences per backbone collapse to a handful of distinct
ones. If your designs "all look the same", check this first.

### MSA vs. single-sequence folding

`NATIVE_MSA_PATH` controls what RF3 conditions on at stage 4. It is resolved by
convention — `../inputs/<pdb_stem>_A.a3m.gz` if that file exists, otherwise `""`
(single-sequence). Build it with `00_make_msa.py`; no config edit needed.

| | MSA | Single-sequence |
|---|---|---|
| Enzyme pLDDT | Higher | Markedly lower |
| Suggested `PLDDT_CUT` | 0.80–0.85 | ~0.70 |
| Best for | Confirming the scaffold survived diffusion | Discriminating between designs |

**Changing mode invalidates your cutoffs.** The single most common way to get
"0 passing designs" from a working pipeline is to fold single-sequence while
keeping an MSA-calibrated `PLDDT_CUT`.

Two things worth understanding about what the MSA is actually doing:

- **The alignment is of the native sequence, but the designs are mutants.**
  Because partial diffusion preserves length and numbering, the native `.a3m`
  is dimensionally compatible with every design and RF3 accepts it silently.
  At your `FLEXIBLE_RESIDUES` positions the alignment therefore argues for the
  *native* residue, not your designed one.
- **`enzyme_plddt` is chainwise.** It averages over the whole of chain A, which
  is mostly untouched native scaffold. With an MSA it will be high for nearly
  every design. It confirms diffusion didn't break the fold; it says little
  about your pocket. The metrics that actually discriminate designs are
  `substrate_min_pae` and `substrate_ipsae` — interface scores against a ligand,
  which has no MSA at all.

**Don't build one MSA per design.** An MSA is a database search result; a
handful of substitutions returns essentially the same homologs. You would spend
hundreds of queries against a free public server to regenerate the alignment you
already have.

### Tuning `PARTIAL_T`

`PARTIAL_T` is in **Angstroms** of coordinate noise added before denoising.

| Value | Effect |
|---|---|
| 3–5 | Very gentle — the flexible residues barely move; lowest risk to the fold |
| 5–10 | Conservative — small local adjustments, stays close to input |
| 10–15 | Moderate — noticeably different backbones, lower pass yield |
| 20+ | Aggressive — large changes; often reduces fold quality |

With a targeted `FLEXIBLE_RESIDUES` set, start around **5**. If the region barely
changes, raise it; if pLDDT is low, lower it (or shrink `FLEXIBLE_RESIDUES`).
Remember `PARTIAL_T` applies to the flexible residues — the rest stays put.

### Engineering specific regions (de-novo loop rebuild)

`FLEXIBLE_RESIDUES` lets a region *move*; to actually *rebuild* a loop from
scratch (a bigger change than partial diffusion can make), override `CONTIG`.
This is the stronger "backbone lever" for reshaping a channel or removing a
blocking loop. If the loop runs from A95 to A115:

```python
# In config.py — replaces the A95-A115 loop with 5-12 brand-new residues
CONTIG = "A4-94,5-12,A116-327"
```

The numeric range `5-12` (no chain prefix) tells RFD3 to design that many
residues from scratch. This is more targeted than increasing `PARTIAL_T` and
directly removes steric bulk from a specific region.

### Recommended settings for production runs

| Setting | Test | Production |
|---|---|---|
| `RFD3_BATCH_SIZE` | 2 | 10 |
| `RFD3_N_BATCHES` | 1 | 10 → 100 backbones |
| `MPNN_BATCH_SIZE` | 2 | 10 |
| `MPNN_NUMBER_OF_BATCHES` | 1 | 1 → 10 seqs/backbone |
| `RF3_NUM_STEPS` | 50 | 200 |
| `RF3_GROUP_SIZE` | 10 | 10 |

---

## Outputs

All outputs go to `$PIPELINE_WORK_ROOT/<your_name>/<experiment>/`
(default `enzyme_design/work/`, see `partial_diffusion/site.py`):

```
<experiment>/
├── configs/          RFD3 + RF3 input JSONs
├── submit/           LSF submit scripts
├── cmds/             Per-task command files
├── logs/             Job stdout/stderr (named by job ID)
├── diffusion_out/    RFD3 backbones (.cif.gz + .json)
│   └── passing/      Filtered backbones that passed quality checks
├── mpnn_out/         LigandMPNN FASTA sequences (one folder per backbone)
├── rf3_out/          RF3 folded complexes + .score files
├── scores/           Metrics CSVs + plots (PAE vs pLDDT, ranked pLDDT)
└── best_designs/     Passing CIFs + best_designs.csv
```

The three metrics that matter in `best_designs.csv`:

| Metric | Meaning | Pass threshold |
|---|---|---|
| `enzyme_plddt` | Fold confidence (0–1) | > 0.80 |
| `substrate_min_pae` | Substrate placement confidence (Å) | < 8.0 |
| `substrate_ipsae` | Enzyme–substrate interface confidence (0–1) | > 0.50 |

`heme_min_pae` and `heme_ipsae` are also reported as a secondary check that
heme coordination geometry was maintained.

---

## Queue notes

- Set both `QUEUE` (GPU) and `CPU_QUEUE` (CPU) in `config.py` — list available
  queues with `bqueues`. `gpua100`/`gpuv100` are the GPU queues (if one is busy,
  try the other); the CPU queue on DTU is usually `hpc`.
- **Never send a non-GPU job to a GPU queue** — it reserves a GPU exclusively and
  blocks it for nothing. The pipeline already splits this automatically; just set
  `CPU_QUEUE` correctly.
- A GPU job pending with *"Host's available GPU resources cannot meet the job's
  requirements"* just means the queue is full — it starts when a GPU frees up.
- Wall times scale with batch counts in `00_submit_all.py`; they are a maximum,
  not a fixed runtime (see [Estimating wall times](#estimating-wall-times)).
- Monitor from the **login node** only (`bstat` / `bjobs` / `bpeek`) — do not
  `ssh` into compute nodes. See [Monitoring your jobs](#monitoring-your-jobs).
- Kill a job: `bkill <jobid>`  (or `bkill 0` to kill all your jobs).
- The pipeline uses `ended()` dependencies so the chain advances even when the
  DTU GPU queue kills a finished job at its run limit (see the technical notes above).
