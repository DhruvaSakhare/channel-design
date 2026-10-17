# Running on an LSF cluster

`00_submit_all.py` submits the pipeline as chained LSF job arrays. This is how
the original campaign ran, and it is kept so those results stay reproducible.

**On a single GPU you do not need any of this** — use
[`scripts/run_local.py`](scripts/run_local.py), which runs the same stages with
no scheduler. `tests/test_stage_parity.py` enforces that the two drivers cover
the same stages. See [README.md](README.md).

It needs two queue names, and has no default for either, because a queue name
means nothing on a cluster that is not yours. If your cluster runs SLURM rather
than LSF, call `run_local.py` from inside your own job script instead.

---

## Full walkthrough — the LSF path

Everything runs from the pipeline root on the cluster's login node. Your outputs
are separated by `YOUR_NAME` and `EXPERIMENT` in `config.py`.

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
[CONFIGURATION.md](CONFIGURATION.md)). Set a **unique
`EXPERIMENT`** name so you don't collide with a teammate's run.

**Step 3 — sanity-check your PDB** (optional but recommended):
```bash
python partial_diffusion/scripts/00_prep_pdb.py --check
```

**Step 4 — build the MSA** (once per enzyme; skip if `<pdb_stem>_A.a3m.gz`
already exists):
```bash
python partial_diffusion/scripts/00_make_msa.py
```
Takes a few minutes, mostly queueing on the ColabFold server. Runs on the login
node — no GPU, no job submission. `config.py` picks the file up by name, so
there is nothing to edit afterwards. See
[Build the MSA for your enzyme](README.md#build-the-msa-for-your-enzyme) for what happens
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
`<WORK>/best_designs/` (see [Outputs](README.md#outputs)).

## Running several experiments at once

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

## Re-submitting after a failure or interruption

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

## Manual step-by-step (for debugging)

Only needed if you want to run a single stage by hand. Run all commands from
`enzyme_design/` (the parent folder), with the conda environment active
(Step 1 above). For normal use, prefer the one-shot `00_submit_all.py`.

**Stage 0 — native MSA** (login node, no job; once per enzyme)
```bash
python partial_diffusion/scripts/00_make_msa.py
# writes <pdb_stem>_A.a3m.gz beside the structure, picked up automatically
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
avoids a quirk of the GPU queue this was developed on (see below). What each stage skips on:

| Stage | Skips when |
|---|---|
| RFD3 | `diffusion_out/` has ≥ expected number of `.cif.gz` files |
| MPNN | Any `.fa` file exists under `mpnn_out/` |
| RF3 input prep | `rf3.sh` + RF3 JSON inputs already exist |
| RF3 folding | Per-task: each array task skips folds whose `out_dir` already has a CIF |
| RF3 scoring | Launcher submits scoring-only if all backbone dirs are folded; exits if `rf3_metrics.csv` exists |

**Dependencies use `ended()`, not `done()`.** On the GPU queue this was developed on, a job that
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
queue (check `bqueues`).

---

## Monitoring your jobs

Everything is done from the **login node** — you never need to `ssh` into a
compute node (check your site's policy; many clusters restrict it).

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


---

## A job sits in RUN until wall-time / dependent jobs stay PEND
On the GPU queue this was developed on, a job that grabs a GPU and finishes quickly may not release
the node — it lingers until wall-time and is killed with `TERM_RUNLIMIT`. The
pipeline handles this two ways: completed stages are skipped at submission (never
launched), and dependencies use `ended()` so a run-limit kill still advances the
chain. If you ever get a genuinely stuck chain, just re-submit:
```bash
bkill 0                                        # kill your queued/stuck jobs
python partial_diffusion/scripts/00_submit_all.py   # skips finished stages, resumes
```

---


---

## Queue notes

- Set both queues. **Not in `config.py`** — the configs do not define them;
  `site.py` does, and it has no default, because a queue name is specific to
  your cluster. List yours with `bqueues`, then pick one of:

  ```bash
  00_submit_all.py --queue <gpu-queue> --cpu-queue <cpu-queue>   # this run only
  export PIPELINE_QUEUE=<gpu-queue> PIPELINE_CPU_QUEUE=<cpu-queue>
  # or put both in envs/site.env, which setup.sh reads
  ```
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
  GPU queue kills a finished job at its run limit (see the technical notes above).
